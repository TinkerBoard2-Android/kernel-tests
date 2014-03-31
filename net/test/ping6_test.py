#!/usr/bin/python

# pylint: disable=g-bad-todo

import errno
import os
import posix
import re
from socket import *  # pylint: disable=wildcard-import
import unittest

import net_test


HAVE_PROC_NET_ICMP6 = os.path.isfile("/proc/net/icmp6")


class Ping6Test(net_test.NetworkTest):

  def setUp(self):
    if net_test.HAVE_IPV6:
      self.ifname = net_test.GetDefaultRouteInterface()
      self.ifindex = net_test.GetInterfaceIndex(self.ifname)
      self.lladdr = net_test.GetLinkAddress(self.ifname, True)
      self.globaladdr = net_test.GetLinkAddress(self.ifname, False)

  def assertValidPingResponse(self, s, data):
    family = s.family

    # Check the data being sent is valid.
    self.assertGreater(len(data), 7, "Not enough data for ping packet")
    if family == AF_INET:
      self.assertTrue(data.startswith("\x08\x00"), "Not an IPv4 echo request")
    elif family == AF_INET6:
      self.assertTrue(data.startswith("\x80\x00"), "Not an IPv4 echo request")
    else:
      self.fail("Unknown socket address family %d" * s.family)

    # Receive the reply.
    rcvd, src = s.recvfrom(32768)
    self.assertNotEqual(0, len(rcvd), "No data received")

    # Check address, ICMP type, and ICMP code.
    if family == AF_INET:
      addr, unused_port = src
      self.assertGreaterEqual(len(addr), len("1.1.1.1"))
      self.assertTrue(rcvd.startswith("\x00\x00"), "Not an IPv4 echo reply")
    else:
      addr, unused_port, flowlabel, scope_id = src
      self.assertGreaterEqual(len(addr), len("::"))
      self.assertTrue(rcvd.startswith("\x81\x00"), "Not an IPv6 echo reply")
      # Check that the flow label is zero and that the scope ID is sane.
      self.assertEqual(flowlabel, 0)
      self.assertLess(scope_id, 100)

    # TODO: check the checksum. We can't do this easily now for ICMPv6 because
    # we don't have the IP addresses so we can't construct the pseudoheader.

    # Check the sequence number and the data.
    self.assertEqual(len(data), len(rcvd))
    self.assertEqual(data[6:].encode("hex"), rcvd[6:].encode("hex"))

  def ReadProcNetSocket(self, protocol):
    # Read file.
    lines = open("/proc/net/%s" % protocol).readlines()

    # Possibly check, and strip, header.
    if protocol in ["icmp6", "raw6", "udp6"]:
      self.assertEqual(net_test.IPV6_SEQ_DGRAM_HEADER, lines[0])
    lines = lines[1:]

    # Check contents.
    if protocol.endswith("6"):
      addrlen = 32
    else:
      addrlen = 8
    regexp = re.compile(r" *(\d+): "                    # bucket
                        "([0-9A-F]{%d}:[0-9A-F]{4}) "   # srcaddr, port
                        "([0-9A-F]{%d}:[0-9A-F]{4}) "   # dstaddr, port
                        "([0-9A-F][0-9A-F]) "           # state
                        "([0-9A-F]{8}:[0-9A-F]{8}) "    # mem
                        "([0-9A-F]{2}:[0-9A-F]{8}) "    # ?
                        "([0-9A-F]{8}) +"               # ?
                        "([0-9]+) +"                    # uid
                        "([0-9]+) +"                    # ?
                        "([0-9]+) +"                    # inode
                        "([0-9]+) +"                    # refcnt
                        "([0-9a-f]+) +"                 # sp
                        "([0-9]+) *$"                   # drops, icmp has spaces
                        % (addrlen, addrlen))
    # Return a list of lists with only source / dest addresses for now.
    out = []
    for line in lines:
      (_, src, dst, state, mem,
       _, _, uid, _, _, refcnt, _, drops) = regexp.match(line).groups()
      out.append([src, dst, state, mem, uid, refcnt, drops])
    return out

  def CheckSockStatFile(self, name, srcaddr, srcport, dstaddr, dstport, state,
                        txmem=0, rxmem=0):
    expected = ["%s:%04X" % (net_test.FormatSockStatAddress(srcaddr), srcport),
                "%s:%04X" % (net_test.FormatSockStatAddress(dstaddr), dstport),
                "%02X" % state,
                "%08X:%08X" % (txmem, rxmem),
                str(os.getuid()), "2", "0"]
    actual = self.ReadProcNetSocket(name)[-1]
    self.assertListEqual(expected, actual)

  def testIPv4SendWithNoConnection(self):
    s = net_test.IPv4PingSocket()
    self.assertRaisesErrno(errno.EDESTADDRREQ, s.send, net_test.IPV4_PING)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6SendWithNoConnection(self):
    s = net_test.IPv6PingSocket()
    self.assertRaisesErrno(errno.EDESTADDRREQ, s.send, net_test.IPV6_PING)

  def testIPv4LoopbackPingWithConnect(self):
    s = net_test.IPv4PingSocket()
    s.connect(("127.0.0.1", 55))
    data = net_test.IPV4_PING + "foobarbaz"
    s.send(data)
    self.assertValidPingResponse(s, data)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6LoopbackPingWithConnect(self):
    s = net_test.IPv6PingSocket()
    s.connect(("::1", 55))
    s.send(net_test.IPV6_PING)
    self.assertValidPingResponse(s, net_test.IPV6_PING)

  def testIPv4PingUsingSendto(self):
    s = net_test.IPv4PingSocket()
    written = s.sendto(net_test.IPV4_PING, (net_test.IPV4_ADDR, 55))
    self.assertEquals(len(net_test.IPV4_PING), written)
    self.assertValidPingResponse(s, net_test.IPV4_PING)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6PingUsingSendto(self):
    s = net_test.IPv6PingSocket()
    written = s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 55))
    self.assertEquals(len(net_test.IPV6_PING), written)
    self.assertValidPingResponse(s, net_test.IPV6_PING)

  def testIPv4NoCrash(self):
    # Python 2.x does not provide either read() or recvmsg.
    s = net_test.IPv4PingSocket()
    written = s.sendto(net_test.IPV4_PING, ("127.0.0.1", 55))
    self.assertEquals(len(net_test.IPV4_PING), written)
    fd = s.fileno()
    reply = posix.read(fd, 4096)
    self.assertEquals(written, len(reply))

  def testIPv6NoCrash(self):
    # Python 2.x does not provide either read() or recvmsg.
    s = net_test.IPv6PingSocket()
    written = s.sendto(net_test.IPV6_PING, ("::1", 55))
    self.assertEquals(len(net_test.IPV6_PING), written)
    fd = s.fileno()
    reply = posix.read(fd, 4096)
    self.assertEquals(written, len(reply))

  def testIPv4Bind(self):
    # Bind to unspecified address.
    s = net_test.IPv4PingSocket()
    s.bind(("0.0.0.0", 544))
    self.assertEquals(("0.0.0.0", 544), s.getsockname())

    # Bind to loopback.
    s = net_test.IPv4PingSocket()
    s.bind(("127.0.0.1", 99))
    self.assertEquals(("127.0.0.1", 99), s.getsockname())

    # Binding twice is not allowed.
    self.assertRaisesErrno(errno.EINVAL, s.bind, ("127.0.0.1", 22))

    # But binding two different sockets to the same ID is allowed.
    s2 = net_test.IPv4PingSocket()
    s2.bind(("127.0.0.1", 99))
    self.assertEquals(("127.0.0.1", 99), s2.getsockname())
    s3 = net_test.IPv4PingSocket()
    s3.bind(("127.0.0.1", 99))
    self.assertEquals(("127.0.0.1", 99), s3.getsockname())

    # If two sockets bind to the same port, the first one to call read() gets
    # the response.
    s4 = net_test.IPv4PingSocket()
    s5 = net_test.IPv4PingSocket()
    s4.bind(("0.0.0.0", 167))
    s5.bind(("0.0.0.0", 167))
    s4.sendto(net_test.IPV4_PING, (net_test.IPV4_ADDR, 44))
    self.assertValidPingResponse(s5, net_test.IPV4_PING)
    net_test.SetSocketTimeout(s4, 100)
    self.assertRaisesErrno(errno.EAGAIN, s4.recv, 32768)

    # If SO_REUSEADDR is turned off, then we get EADDRINUSE.
    s6 = net_test.IPv4PingSocket()
    s4.setsockopt(SOL_SOCKET, SO_REUSEADDR, 0)
    self.assertRaisesErrno(errno.EADDRINUSE, s6.bind, ("0.0.0.0", 167))

    # Can't bind after sendto.
    s = net_test.IPv4PingSocket()
    s.sendto(net_test.IPV4_PING, (net_test.IPV4_ADDR, 9132))
    self.assertRaisesErrno(errno.EINVAL, s.bind, ("0.0.0.0", 5429))

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6Bind(self):
    # Bind to unspecified address.
    s = net_test.IPv6PingSocket()
    s.bind(("::", 769))
    self.assertEquals(("::", 769, 0, 0), s.getsockname())

    # Bind to loopback.
    s = net_test.IPv6PingSocket()
    s.bind(("::1", 99))
    self.assertEquals(("::1", 99, 0, 0), s.getsockname())

    # Binding twice is not allowed.
    self.assertRaisesErrno(errno.EINVAL, s.bind, ("::1", 22))

    # But binding two different sockets to the same ID is allowed.
    s2 = net_test.IPv6PingSocket()
    s2.bind(("::1", 99))
    self.assertEquals(("::1", 99, 0, 0), s2.getsockname())
    s3 = net_test.IPv6PingSocket()
    s3.bind(("::1", 99))
    self.assertEquals(("::1", 99, 0, 0), s3.getsockname())

    # Binding both IPv4 and IPv6 to the same socket works.
    s4 = net_test.IPv4PingSocket()
    s6 = net_test.IPv6PingSocket()
    s4.bind(("0.0.0.0", 444))
    s6.bind(("::", 666, 0, 0))

    # Can't bind after sendto.
    s = net_test.IPv6PingSocket()
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 9132))
    self.assertRaisesErrno(errno.EINVAL, s.bind, ("::", 5429))

  def testIPv4InvalidBind(self):
    s = net_test.IPv4PingSocket()
    self.assertRaisesErrno(errno.EADDRNOTAVAIL,
                           s.bind, ("255.255.255.255", 1026))
    self.assertRaisesErrno(errno.EADDRNOTAVAIL,
                           s.bind, ("224.0.0.1", 651))
    # Binding to an address we don't have only works with IP_TRANSPARENT.
    self.assertRaisesErrno(errno.EADDRNOTAVAIL,
                           s.bind, (net_test.IPV4_ADDR, 651))
    try:
      s.setsockopt(SOL_IP, net_test.IP_TRANSPARENT, 1)
      s.bind((net_test.IPV4_ADDR, 651))
    except IOError, e:
      if e.errno == errno.EACCES:
        pass  # We're not root. let it go for now.

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6InvalidBind(self):
    s = net_test.IPv6PingSocket()
    self.assertRaisesErrno(errno.EINVAL,
                           s.bind, ("ff02::2", 1026))

    # Binding to an address we don't have only works with IPV6_TRANSPARENT.
    self.assertRaisesErrno(errno.EADDRNOTAVAIL,
                           s.bind, (net_test.IPV6_ADDR, 651))
    try:
      s.setsockopt(net_test.SOL_IPV6, net_test.IPV6_TRANSPARENT, 1)
      s.bind((net_test.IPV6_ADDR, 651))
    except IOError, e:
      if e.errno == errno.EACCES:
        pass  # We're not root. let it go for now.

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6ScopedBind(self):
    # Can't bind to a link-local address without a scope ID.
    s = net_test.IPv6PingSocket()
    self.assertRaisesErrno(errno.EINVAL,
                           s.bind, (self.lladdr, 1026, 0, 0))

    # Binding to a link-local address with a scope ID works, and the scope ID is
    # returned by a subsequent getsockname. Interestingly, Python's getsockname
    # returns "fe80:1%foo", even though it does not understand it.
    expected = self.lladdr + "%" + self.ifname
    s.bind((self.lladdr, 4646, 0, self.ifindex))
    self.assertEquals((expected, 4646, 0, self.ifindex), s.getsockname())

    # Of course, for the above to work the address actually has to be configured
    # on the machine.
    self.assertRaisesErrno(errno.EADDRNOTAVAIL,
                           s.bind, ("fe80::f00", 1026, 0, 1))

    # Scope IDs on non-link-local addresses are silently ignored.
    s = net_test.IPv6PingSocket()
    s.bind(("::1", 1234, 0, 1))
    self.assertEquals(("::1", 1234, 0, 0), s.getsockname())

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testBindAffectsIdentifier(self):
    s = net_test.IPv6PingSocket()
    s.bind((self.globaladdr, 0xf976))
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 55))
    self.assertEquals("\xf9\x76", s.recv(32768)[4:6])

    s = net_test.IPv6PingSocket()
    s.bind((self.globaladdr, 0xace))
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 55))
    self.assertEquals("\x0a\xce", s.recv(32768)[4:6])

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testLinkLocalAddress(self):
    s = net_test.IPv6PingSocket()
    # Sending to a link-local address with no scope fails with EINVAL.
    self.assertRaisesErrno(errno.EINVAL,
                           s.sendto, net_test.IPV6_PING, ("fe80::1", 55))
    # Sending to link-local address with a scope succeeds. Note that Python
    # doesn't understand the "fe80::1%lo" format, even though it returns it.
    s.sendto(net_test.IPV6_PING, ("fe80::1", 55, 0, self.ifindex))
    # No exceptions? Good.

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testMappedAddressFails(self):
    s = net_test.IPv6PingSocket()
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 55))
    self.assertValidPingResponse(s, net_test.IPV6_PING)
    s.sendto(net_test.IPV6_PING, ("2001:4860:4860::8844", 55))
    self.assertValidPingResponse(s, net_test.IPV6_PING)
    self.assertRaisesErrno(errno.EINVAL, s.sendto, net_test.IPV6_PING,
                           ("::ffff:192.0.2.1", 55))

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testFlowLabel(self):
    s = net_test.IPv6PingSocket()
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 93, 0xdead, 0))
    self.assertValidPingResponse(s, net_test.IPV6_PING)  # Checks flow label==0.

    s.setsockopt(net_test.SOL_IPV6, net_test.IPV6_FLOWINFO_SEND, 1)
    self.assertEqual(1, s.getsockopt(net_test.SOL_IPV6,
                                     net_test.IPV6_FLOWINFO_SEND))
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 93, 0xdead, 0))
    _, src = s.recvfrom(32768)
    _, _, flowlabel, _ = src
    self.assertEqual(0, flowlabel & 0xfffff)

  def testIPv4Error(self):
    s = net_test.IPv4PingSocket()
    s.setsockopt(SOL_IP, IP_TTL, 2)
    s.setsockopt(SOL_IP, net_test.IP_RECVERR, 1)
    s.sendto(net_test.IPV4_PING, (net_test.IPV4_ADDR, 55))
    # We can't check the actual error because Python 2.7 doesn't implement
    # recvmsg, but we can at least check that the socket returns an error.
    self.assertRaisesErrno(errno.EHOSTUNREACH, s.recv, 32768)  # No response.

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6Error(self):
    s = net_test.IPv6PingSocket()
    s.setsockopt(net_test.SOL_IPV6, IPV6_UNICAST_HOPS, 2)
    s.setsockopt(net_test.SOL_IPV6, net_test.IPV6_RECVERR, 1)
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 55))
    # We can't check the actual error because Python 2.7 doesn't implement
    # recvmsg, but we can at least check that the socket returns an error.
    self.assertRaisesErrno(errno.EHOSTUNREACH, s.recv, 32768)  # No response.

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6MulticastPing(self):
    s = net_test.IPv6PingSocket()
    # Send a multicast ping and check we get at least one duplicate.
    s.sendto(net_test.IPV6_PING, ("ff02::1", 55, 0, self.ifindex))
    self.assertValidPingResponse(s, net_test.IPV6_PING)
    self.assertValidPingResponse(s, net_test.IPV6_PING)

  def testIPv4LargePacket(self):
    s = net_test.IPv4PingSocket()
    data = net_test.IPV4_PING + 20000 * "a"
    s.sendto(data, ("127.0.0.1", 987))
    self.assertValidPingResponse(s, data)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testIPv6LargePacket(self):
    s = net_test.IPv6PingSocket()
    s.bind(("::", 0xace))
    data = net_test.IPV6_PING + "\x01" + 19994 * "\x00" + "aaaaa"
    s.sendto(data, ("::1", 953))

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  @unittest.skipUnless(HAVE_PROC_NET_ICMP6, "skipping: no /proc/net/icmp6")
  def testIcmpSocketsNotInIcmp6(self):
    numrows = len(self.ReadProcNetSocket("icmp"))
    numrows6 = len(self.ReadProcNetSocket("icmp6"))
    s = net_test.Socket(AF_INET, SOCK_DGRAM, IPPROTO_ICMP)
    s.bind(("127.0.0.1", 0xace))
    s.connect(("127.0.0.1", 0xbeef))
    self.assertEquals(numrows + 1, len(self.ReadProcNetSocket("icmp")))
    self.assertEquals(numrows6, len(self.ReadProcNetSocket("icmp6")))

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  @unittest.skipUnless(HAVE_PROC_NET_ICMP6, "skipping: no /proc/net/icmp6")
  def testIcmp6SocketsNotInIcmp(self):
    numrows = len(self.ReadProcNetSocket("icmp"))
    numrows6 = len(self.ReadProcNetSocket("icmp6"))
    s = net_test.IPv6PingSocket()
    s.bind(("::1", 0xace))
    s.connect(("::1", 0xbeef))
    self.assertEquals(numrows, len(self.ReadProcNetSocket("icmp")))
    self.assertEquals(numrows6 + 1, len(self.ReadProcNetSocket("icmp6")))

  def testProcNetIcmp(self):
    s = net_test.Socket(AF_INET, SOCK_DGRAM, IPPROTO_ICMP)
    s.bind(("127.0.0.1", 0xace))
    s.connect(("127.0.0.1", 0xbeef))
    self.CheckSockStatFile("icmp", "127.0.0.1", 0xace, "127.0.0.1", 0xbeef, 1)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  @unittest.skipUnless(HAVE_PROC_NET_ICMP6, "skipping: no /proc/net/icmp6")
  def testProcNetIcmp6(self):
    numrows6 = len(self.ReadProcNetSocket("icmp6"))
    s = net_test.IPv6PingSocket()
    s.bind(("::1", 0xace))
    s.connect(("::1", 0xbeef))
    self.CheckSockStatFile("icmp6", "::1", 0xace, "::1", 0xbeef, 1)

    # Check the row goes away when the socket is closed.
    s.close()
    self.assertEquals(numrows6, len(self.ReadProcNetSocket("icmp6")))

    # Try send, bind and connect to check the addresses and the state.
    s = net_test.IPv6PingSocket()
    self.assertEqual(0, len(self.ReadProcNetSocket("icmp6")))
    s.sendto(net_test.IPV6_PING, (net_test.IPV6_ADDR, 12345))
    self.assertEqual(1, len(self.ReadProcNetSocket("icmp6")))

    # Can't bind after sendto, apparently.
    s = net_test.IPv6PingSocket()
    self.assertEqual(0, len(self.ReadProcNetSocket("icmp6")))
    s.bind((self.lladdr, 0xd00d, 0, self.ifindex))
    self.CheckSockStatFile("icmp6", self.lladdr, 0xd00d, "::", 0, 7)

    # Check receive bytes.
    s.connect(("ff02::1", 0xdead))
    self.CheckSockStatFile("icmp6", self.lladdr, 0xd00d, "ff02::1", 0xdead, 1)
    s.send(net_test.IPV6_PING)
    self.CheckSockStatFile("icmp6", self.lladdr, 0xd00d, "ff02::1", 0xdead, 1,
                           txmem=0, rxmem=0x880)
    self.assertValidPingResponse(s, net_test.IPV6_PING)
    self.CheckSockStatFile("icmp6", self.lladdr, 0xd00d, "ff02::1", 0xdead, 1,
                           txmem=0, rxmem=0)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testProcNetUdp6(self):
    s = net_test.Socket(AF_INET6, SOCK_DGRAM, IPPROTO_UDP)
    s.bind(("::1", 0xace))
    s.connect(("::1", 0xbeef))
    self.CheckSockStatFile("udp6", "::1", 0xace, "::1", 0xbeef, 1)

  @unittest.skipUnless(net_test.HAVE_IPV6, "skipping: no IPv6")
  def testProcNetRaw6(self):
    s = net_test.Socket(AF_INET6, SOCK_RAW, IPPROTO_RAW)
    s.bind(("::1", 0xace))
    s.connect(("::1", 0xbeef))
    self.CheckSockStatFile("raw6", "::1", 0xff, "::1", 0, 1)


if __name__ == "__main__":
  unittest.main()

