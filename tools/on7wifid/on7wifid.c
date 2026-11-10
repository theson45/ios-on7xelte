/*
 * on7wifid: the J7 Prime's Wi-Fi (the kernel's en0, xnu bsd/dev/on7xelte_wifi.c, patch 0178) as a network
 * service iOS uses, and auto-join at boot.
 *
 *  - joins: writes "auto" to kern.on7xelte_wifi (root only): the kernel loads the firmware if it is not running
 *    and joins the network 'wifi join ... save' kept (SSID + PMK, root only, never the password). Again while
 *    there is no link: 30 s after a failure, up to 5 min after many; every 60 s with nothing saved.
 *  - publishes: the kernel's DHCP lease (kern.on7xelte_wifi_lease) in configd's dynamic store as
 *    IPConfiguration would (after ios-b0s tools/phone/netsvcd.c): State:/Network/Service/SVC/{IPv4,DNS} and
 *    State:/Network/Interface/en0/IPv4, so IPMonitor makes it primary and mDNSResponder gets the DNS server;
 *    again whenever the keys are gone (configd restarted) or the lease changed; removed when the link goes.
 *  - says what it does in the kernel log ("USB> on7wifid: ...", kern.on7xelte_wifi "log TEXT"): its stdout goes
 *    nowhere.
 *
 *   on7wifid            daemon (launchd job com.on7xelte.wifid)
 *   on7wifid show       the lease and the store keys
 * Signed with on7wifid-ents.plist (SCDynamicStore write access).
 */
#include <CoreFoundation/CoreFoundation.h>
#include <arpa/inet.h>
#include <errno.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>
#include <time.h>
#include <unistd.h>

/* SystemConfiguration has these on iOS; the SDK only marks them unavailable */
typedef const struct __SCDynamicStore *SCDynamicStoreRef;
extern SCDynamicStoreRef SCDynamicStoreCreate(CFAllocatorRef, CFStringRef, void *, void *);
extern CFPropertyListRef SCDynamicStoreCopyValue(SCDynamicStoreRef, CFStringRef);
extern Boolean SCDynamicStoreSetMultiple(SCDynamicStoreRef, CFDictionaryRef, CFArrayRef, CFArrayRef);
extern int SCError(void);
extern const char *SCErrorString(int);

#define SVC     "0E7F1A00-0000-4000-8000-000000000001"  /* our id for the Wi-Fi service */
#define FALLBACK_DNS "1.1.1.1"

/* kern.on7xelte_wifi_lease (on7xelte_wifi.c struct on7_wifi_lease) */
struct lease {
	uint32_t ver, link, state, on_if, ip, mask, gw, dns, lease;
	char ifname[16];
};

static void
say(const char *fmt, ...)
{
	char line[160], msg[168];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(line, sizeof(line), fmt, ap);
	va_end(ap);
	printf("on7wifid: %s\n", line);
	fflush(stdout);
	snprintf(msg, sizeof(msg), "log %s", line);
	(void)sysctlbyname("kern.on7xelte_wifi", NULL, NULL, msg, strlen(msg) + 1);
}

static int
kcmd(const char *c)
{
	return sysctlbyname("kern.on7xelte_wifi", NULL, NULL, (void *)(uintptr_t)c, strlen(c) + 1) == 0 ? 0 : errno;
}

static int
get_lease(struct lease *l)
{
	size_t n = sizeof(*l);
	memset(l, 0, sizeof(*l));
	if (sysctlbyname("kern.on7xelte_wifi_lease", l, &n, NULL, 0) != 0 || n != sizeof(*l) || l->ver != 1) {
		return 0;
	}
	l->ifname[sizeof(l->ifname) - 1] = 0;
	return 1;
}

static void
ipstr(uint32_t a, char *s, size_t n)
{
	snprintf(s, n, "%u.%u.%u.%u", a >> 24, (a >> 16) & 255, (a >> 8) & 255, a & 255);
}

static CFStringRef
str(const char *s)
{
	return CFStringCreateWithCString(NULL, s, kCFStringEncodingUTF8);
}

static CFArrayRef
arr(int n, const char **v)
{
	CFStringRef s[4];
	for (int i = 0; i < n; i++) {
		s[i] = str(v[i]);
	}
	CFArrayRef a = CFArrayCreate(NULL, (const void **)s, n, &kCFTypeArrayCallBacks);
	for (int i = 0; i < n; i++) {
		CFRelease(s[i]);
	}
	return a;
}

/* a dictionary of n keys; takes over the values */
static CFDictionaryRef
dict(int n, const char **k, CFTypeRef *v)
{
	CFStringRef ks[8];
	for (int i = 0; i < n; i++) {
		ks[i] = str(k[i]);
	}
	CFDictionaryRef d = CFDictionaryCreate(NULL, (const void **)ks, (const void **)v, n,
	    &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
	for (int i = 0; i < n; i++) {
		CFRelease(ks[i]);
		CFRelease(v[i]);
	}
	return d;
}

static char k_svc4[96], k_dns[96], k_if4[96];

static void
make_keys(const char *ifname)
{
	snprintf(k_svc4, sizeof(k_svc4), "State:/Network/Service/" SVC "/IPv4");
	snprintf(k_dns, sizeof(k_dns), "State:/Network/Service/" SVC "/DNS");
	snprintf(k_if4, sizeof(k_if4), "State:/Network/Interface/%s/IPv4", ifname);
}

static int
publish(SCDynamicStoreRef st, const struct lease *l)
{
	char a[16], m[16], g[16], d[16];
	ipstr(l->ip, a, sizeof(a));
	ipstr(l->mask, m, sizeof(m));
	ipstr(l->gw, g, sizeof(g));
	ipstr(l->dns ? l->dns : l->gw, d, sizeof(d));
	const char *addr[] = { a }, *mask[] = { m }, *dns[] = { d, FALLBACK_DNS };
	const char *k4[] = { "Addresses", "SubnetMasks", "InterfaceName", "ConfigMethod", "Router" };
	CFTypeRef v4[] = { arr(1, addr), arr(1, mask), str(l->ifname), str("DHCP"), str(g) };
	const char *kd[] = { "ServerAddresses" };
	CFTypeRef vd[] = { arr(strcmp(d, FALLBACK_DNS) ? 2 : 1, dns) };
	const char *ki[] = { "Addresses", "SubnetMasks" };
	CFTypeRef vi[] = { arr(1, addr), arr(1, mask) };
	const char *keys[] = { k_svc4, k_dns, k_if4 };
	CFTypeRef vals[] = { dict(l->gw ? 5 : 4, k4, v4), dict(1, kd, vd), dict(2, ki, vi) };
	if (!l->gw) {           /* no router: the value the dictionary did not take */
		CFRelease(v4[4]);
	}
	CFDictionaryRef set = dict(3, keys, vals);
	Boolean ok = SCDynamicStoreSetMultiple(st, set, NULL, NULL);
	CFRelease(set);
	say("published %s %s/%s router %s DNS %s%s: %s", l->ifname, a, m, g, d,
	    strcmp(d, FALLBACK_DNS) ? " " FALLBACK_DNS : "", ok ? "ok" : SCErrorString(SCError()));
	return ok;
}

static void
unpublish(SCDynamicStoreRef st)
{
	const char *keys[] = { k_svc4, k_dns, k_if4 };
	CFArrayRef gone = arr(3, keys);
	Boolean ok = SCDynamicStoreSetMultiple(st, NULL, gone, NULL);
	CFRelease(gone);
	say("removed the Wi-Fi service: %s", ok ? "ok" : SCErrorString(SCError()));
}

static int
present(SCDynamicStoreRef st)
{
	const char *keys[] = { k_svc4, k_dns, k_if4 };
	int all = 1;
	for (int i = 0; i < 3; i++) {
		CFStringRef k = str(keys[i]);
		CFPropertyListRef v = SCDynamicStoreCopyValue(st, k);
		CFRelease(k);
		if (v) {
			CFRelease(v);
		} else {
			all = 0;
		}
	}
	return all;
}

static SCDynamicStoreRef
store(void)
{
	SCDynamicStoreRef st;
	int waited = 0;
	while ((st = SCDynamicStoreCreate(NULL, CFSTR("on7wifid"), NULL, NULL)) == NULL) {
		if (waited++ == 0) {
			say("waiting for configd");
		}
		sleep(2);
	}
	return st;
}

static void
show(SCDynamicStoreRef st)
{
	struct lease l;
	if (!get_lease(&l)) {
		printf("no lease sysctl (kernel without 0178?)\n");
		return;
	}
	char a[16], g[16], d[16];
	ipstr(l.ip, a, sizeof(a));
	ipstr(l.gw, g, sizeof(g));
	ipstr(l.dns, d, sizeof(d));
	printf("%s link %u DHCP state %u on interface %u: %s router %s DNS %s lease %u\n", l.ifname[0] ? l.ifname : "-",
	    l.link, l.state, l.on_if, a, g, d, l.lease);
	make_keys(l.ifname[0] ? l.ifname : "en0");
	const char *keys[] = { k_svc4, k_dns, k_if4, "State:/Network/Global/IPv4", "State:/Network/Global/DNS" };
	for (int i = 0; i < 5; i++) {
		CFStringRef k = str(keys[i]);
		CFPropertyListRef v = SCDynamicStoreCopyValue(st, k);
		CFRelease(k);
		printf("%s: %s\n", keys[i], v ? "" : "(none)");
		if (v) {
			CFShow(v);
			CFRelease(v);
		}
	}
}

int
main(int argc, char **argv)
{
	SCDynamicStoreRef st = store();
	if (argc > 1 && strcmp(argv[1], "show") == 0) {
		show(st);
		return 0;
	}
	say("started");
	struct lease cur, pub;
	int published = 0, fails = 0, last_err = -1;
	time_t next_auto = 0;
	memset(&pub, 0, sizeof(pub));
	for (;;) {
		int have = get_lease(&cur);
		int ready = have && cur.link && cur.state == 3 && cur.on_if && cur.ifname[0];
		if (ready) {
			fails = 0;
			if (!published || memcmp(&cur, &pub, offsetof(struct lease, lease)) || strcmp(cur.ifname, pub.ifname)) {
				if (published && strcmp(cur.ifname, pub.ifname)) {
					unpublish(st);
				}
				make_keys(cur.ifname);
				publish(st, &cur);
				pub = cur;
				published = 1;
			} else if (!present(st)) {
				say("keys gone (configd restarted?): publishing again");
				publish(st, &cur);
			}
		} else {
			if (published) {
				unpublish(st);
				published = 0;
			}
			time_t now = time(NULL);
			if (!(have && cur.link) && now >= next_auto) {
				int err = kcmd("auto");
				if (err != last_err || err == 0) {
					say("auto-join: %s", err == 0 ? "joined" : err == ENOENT ? "no saved network" :
					    err == ECANCELED ? "Wi-Fi turned off by hand" : strerror(err));
					last_err = err;
				}
				if (err == 0) {
					fails = 0;
					next_auto = now + 30;
				} else if (err == ENOENT || err == ECANCELED) {
					next_auto = now + 60;
				} else {
					fails++;
					next_auto = now + (fails < 4 ? 30 : fails < 10 ? 120 : 300);
				}
			}
		}
		sleep(2);
	}
}
