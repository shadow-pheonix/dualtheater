package dev.dualtheater.tv;

import org.junit.Test;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.Assert.*;

public class TimingClientTest {
    private static final String TOKEN = "test-session-token";
    static class Endpoint implements AutoCloseable {
        final ServerSocket tcp = new ServerSocket(0, 4, InetAddress.getLoopbackAddress());
        final DatagramSocket udp = new DatagramSocket(0, InetAddress.getLoopbackAddress());
        final AtomicInteger tcpCount = new AtomicInteger(), hellos = new AtomicInteger(), pongs = new AtomicInteger();
        final AtomicReference<Throwable> error = new AtomicReference<>();
        volatile boolean closed, mute;
        Socket accepted;
        Endpoint(String response) throws Exception {
            tcp.setSoTimeout(200); udp.setSoTimeout(100);
            daemon(() -> {
                while (!closed) try {
                    Socket s = tcp.accept(); accepted = s; tcpCount.incrementAndGet();
                    try (s) {
                        JSONObject hello = new JSONObject(new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8)).readLine());
                        assertEquals("timing", hello.getString("role")); assertEquals(TOKEN, hello.getString("token"));
                        s.getOutputStream().write("{\"op\":\"timing_ready\",\"version\":2}\n".getBytes(StandardCharsets.UTF_8));
                        while (!closed && s.getInputStream().read() != -1) {}
                    }
                } catch (SocketTimeoutException retry) { }
                catch (Throwable failure) { if (!closed) error.compareAndSet(null, failure); }
            });
            daemon(() -> {
                byte[] bytes = new byte[2049];
                while (!closed) try {
                    DatagramPacket packet = new DatagramPacket(bytes, bytes.length); udp.receive(packet);
                    JSONObject msg = new JSONObject(new String(bytes, 0, packet.getLength(), StandardCharsets.UTF_8));
                    if ("pong".equals(msg.optString("op"))) { pongs.incrementAndGet(); continue; }
                    hellos.incrementAndGet();
                    if (response.equals("none") || mute) continue;
                    JSONObject reply = new JSONObject().put("token", response.equals("wrong") ? "wrong-token" : TOKEN);
                    if (response.equals("ping")) reply.put("op", "ping").put("t0", System.nanoTime());
                    else reply.put("op", "timing_ready").put("version", 3);
                    byte[] payload = reply.toString().getBytes(StandardCharsets.UTF_8);
                    udp.send(new DatagramPacket(payload, payload.length, packet.getSocketAddress()));
                } catch (SocketTimeoutException retry) { }
                catch (Throwable failure) { if (!closed) error.compareAndSet(null, failure); }
            });
        }
        void check() { if (error.get() != null) throw new AssertionError(error.get()); }
        public void close() throws Exception {
            closed = true; tcp.close(); udp.close(); if (accepted != null) accepted.close(); check();
        }
    }
    static void daemon(Runnable task) { Thread t = new Thread(task); t.setDaemon(true); t.start(); }
    static void connect(TimingClient client, Endpoint endpoint, CountDownLatch ready, AtomicInteger failures) {
        client.connect("127.0.0.1", endpoint.udp.getLocalPort(), TOKEN, new RemoteTimeline(),
            ready::countDown, failures::incrementAndGet, true, endpoint.tcp.getLocalPort());
    }
    @Test public void blockedUdpFallsBackWithinPreparationBudget() throws Exception {
        try (Endpoint endpoint = new Endpoint("none"); TimingClient client = new TimingClient()) {
            CountDownLatch ready = new CountDownLatch(1); AtomicInteger failures = new AtomicInteger();
            long started = System.nanoTime(); connect(client, endpoint, ready, failures);
            assertTrue(ready.await(5, TimeUnit.SECONDS));
            assertTrue(System.nanoTime() - started >= 2_400_000_000L);
            assertEquals(1, endpoint.tcpCount.get()); assertEquals(0, failures.get()); assertTrue(endpoint.hellos.get() >= 8);
        }
    }
    @Test public void wrongTokenTrafficCannotExtendUdpNegotiation() throws Exception {
        try (Endpoint endpoint = new Endpoint("wrong"); TimingClient client = new TimingClient()) {
            CountDownLatch ready = new CountDownLatch(1); AtomicInteger failures = new AtomicInteger();
            connect(client, endpoint, ready, failures); assertTrue(ready.await(5, TimeUnit.SECONDS));
            assertEquals(1, endpoint.tcpCount.get()); assertEquals(0, failures.get());
        }
    }
    @Test public void validUdpReadyStaysOnUdp() throws Exception {
        try (Endpoint endpoint = new Endpoint("ready"); TimingClient client = new TimingClient()) {
            CountDownLatch ready = new CountDownLatch(1); connect(client, endpoint, ready, new AtomicInteger());
            assertTrue(ready.await(1, TimeUnit.SECONDS)); Thread.sleep(350);
            assertEquals(0, endpoint.tcpCount.get());
        }
    }
    @Test public void lostReadyWithValidSessionPingStaysOnUdp() throws Exception {
        try (Endpoint endpoint = new Endpoint("ping"); TimingClient client = new TimingClient()) {
            CountDownLatch ready = new CountDownLatch(1); connect(client, endpoint, ready, new AtomicInteger());
            assertTrue(ready.await(1, TimeUnit.SECONDS)); Thread.sleep(350);
            assertTrue(endpoint.pongs.get() >= 1); assertEquals(0, endpoint.tcpCount.get());
        }
    }
    @Test public void cancellationDuringNegotiationCannotStartFallback() throws Exception {
        try (Endpoint endpoint = new Endpoint("none"); TimingClient client = new TimingClient()) {
            CountDownLatch ready = new CountDownLatch(1); connect(client, endpoint, ready, new AtomicInteger());
            long deadline = System.nanoTime() + 1_000_000_000L;
            while (endpoint.hellos.get() == 0 && System.nanoTime() < deadline) Thread.sleep(10);
            assertTrue(endpoint.hellos.get() > 0); client.close(); Thread.sleep(2800);
            assertEquals(0, endpoint.tcpCount.get()); assertEquals(1, ready.getCount());
        }
    }
    @Test public void establishedUdpLossReportsFailureBeforeAnyFallback() throws Exception {
        try (Endpoint endpoint = new Endpoint("ready"); TimingClient client = new TimingClient()) {
            CountDownLatch ready = new CountDownLatch(1); AtomicInteger failures = new AtomicInteger();
            connect(client, endpoint, ready, failures); assertTrue(ready.await(1, TimeUnit.SECONDS)); endpoint.mute = true;
            long deadline = System.nanoTime() + 4_000_000_000L;
            while (failures.get() == 0 && System.nanoTime() < deadline) Thread.sleep(20);
            assertTrue(failures.get() > 0); assertEquals(0, endpoint.tcpCount.get());
        }
    }
}
