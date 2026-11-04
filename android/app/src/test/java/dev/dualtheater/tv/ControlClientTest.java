package dev.dualtheater.tv;

import org.junit.Test;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.Assert.*;

public class ControlClientTest {
    static class Listener implements ControlClient.Listener {
        final AtomicInteger disconnects = new AtomicInteger();
        final CountDownLatch disconnected = new CountDownLatch(1);
        public void onMessage(JSONObject value) {}
        public void onDisconnected(String reason) { disconnects.incrementAndGet(); disconnected.countDown(); }
    }

    @Test public void closeBeforeSocketAdoptionCannotConnectOrLeak() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), closed = new CountDownLatch(1);
        AtomicInteger connects = new AtomicInteger(); Listener listener = new Listener();
        Socket socket = new Socket() {
            @Override public void connect(SocketAddress address, int timeout) { connects.incrementAndGet(); }
            @Override public synchronized void close() throws IOException { super.close(); closed.countDown(); }
        };
        ControlClient client = new ControlClient(listener, () -> {
            entered.countDown();
            try { release.await(2, TimeUnit.SECONDS); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            return socket;
        });
        client.connect("127.0.0.1", 1, "fixture", "fixture"); assertTrue(entered.await(1, TimeUnit.SECONDS));
        client.close(); release.countDown(); assertTrue(closed.await(1, TimeUnit.SECONDS));
        assertEquals(0, connects.get()); assertEquals(1, listener.disconnects.get()); assertTrue(socket.isClosed());
    }

    @Test public void cancellationDuringConnectClosesAdoptedSocketOnce() throws Exception {
        CountDownLatch connecting = new CountDownLatch(1), closed = new CountDownLatch(1); Listener listener = new Listener();
        Socket socket = new Socket() {
            @Override public void connect(SocketAddress address, int timeout) throws IOException {
                connecting.countDown();
                try { closed.await(1, TimeUnit.SECONDS); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                throw new SocketException("closed");
            }
            @Override public synchronized void close() throws IOException { super.close(); closed.countDown(); }
        };
        ControlClient client = new ControlClient(listener, () -> socket);
        client.connect("127.0.0.1", 1, "fixture", "fixture"); assertTrue(connecting.await(1, TimeUnit.SECONDS));
        client.close(); assertTrue(closed.await(1, TimeUnit.SECONDS)); client.close();
        assertEquals(1, listener.disconnects.get());
    }

    @Test public void normalEofClosesSocketAndNotifiesOnce() throws Exception {
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getLoopbackAddress())) {
            Listener listener = new Listener(); Socket socket = new Socket();
            ControlClient client = new ControlClient(listener, () -> socket);
            client.connect("127.0.0.1", server.getLocalPort(), "fixture", "fixture");
            try (Socket accepted = server.accept()) {
                assertNotNull(new BufferedReader(new InputStreamReader(accepted.getInputStream())).readLine());
            }
            assertTrue(listener.disconnected.await(1, TimeUnit.SECONDS)); assertTrue(socket.isClosed());
            client.close(); assertEquals(1, listener.disconnects.get());
        }
    }
}
