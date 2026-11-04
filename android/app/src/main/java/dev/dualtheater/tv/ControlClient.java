package dev.dualtheater.tv;

import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;

/** One authenticated connection. Bounded output; no silent replay after disconnect. */
final class ControlClient implements AutoCloseable {
    interface Listener {
        void onMessage(JSONObject message);
        void onDisconnected(String reason);
    }
    private final Listener listener;
    private final BlockingQueue<String> outbound = new ArrayBlockingQueue<>(64);
    private final AtomicBoolean closed = new AtomicBoolean(false);
    private final Object lifecycle = new Object();
    private final Supplier<Socket> socketFactory;
    private boolean started;
    private volatile Socket socket;
    private Thread readerThread, writerThread;

    ControlClient(Listener listener) { this(listener, Socket::new); }
    ControlClient(Listener listener, Supplier<Socket> socketFactory) {
        this.listener = listener; this.socketFactory = socketFactory;
    }

    void connect(String host, int port, String token, String clientId) {
        synchronized (lifecycle) {
            if (started || closed.get()) return;
            started = true;
        }
        readerThread = new Thread(() -> {
            try (Socket s = socketFactory.get()) {
                synchronized (lifecycle) {
                    if (closed.get()) return;
                    socket = s;
                }
                s.connect(new InetSocketAddress(host, port), 5000);
                if (closed.get()) return;
                s.setTcpNoDelay(true);
                s.setSoTimeout(4000);
                BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(s.getOutputStream(), StandardCharsets.UTF_8));
                JSONObject hello = new JSONObject().put("op", "hello").put("version", 1)
                    .put("client_protocol", 1)
                    .put("timing_protocol", 2)
                    .put("timing_datagrams", true)
                    .put("remote_controls", true)
                    .put("client_id", clientId)
                    .put("token", token).put("device", android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL);
                writer.write(hello.toString()); writer.newLine(); writer.flush();
                writerThread = new Thread(() -> {
                    try {
                        while (!closed.get()) {
                            String line = outbound.take();
                            writer.write(line); writer.newLine(); writer.flush();
                        }
                    } catch (Exception e) { disconnect("Control writer: " + e.getMessage()); }
                }, "dualtheater-writer");
                writerThread.start();
                BufferedReader reader = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
                while (!closed.get()) {
                    // Enforce a limit before allocating an unbounded line.
                    StringBuilder line = new StringBuilder();
                    int c;
                    while ((c = reader.read()) != -1 && c != '\n') {
                        if (line.length() >= 65536) throw new IOException("Oversized control message");
                        line.append((char)c);
                    }
                    if (c == -1) throw new EOFException("Host disconnected");
                    JSONObject msg = new JSONObject(line.toString());
                    if ("ping".equals(msg.optString("op"))) {
                        long t1 = System.nanoTime();
                        send(new JSONObject().put("op", "pong").put("t0", msg.getLong("t0"))
                             .put("t1", t1).put("t2", System.nanoTime()));
                    } else listener.onMessage(msg);
                }
            } catch (Exception e) { disconnect(e.getMessage()); }
            finally { disconnect("Host disconnected"); }
        }, "dualtheater-reader");
        readerThread.start();
    }

    void send(JSONObject message) {
        String line = message.toString();
        if (line.getBytes(StandardCharsets.UTF_8).length > StatusPayload.MAX_BYTES) {
            disconnect("Oversized control output"); return;
        }
        if (!closed.get() && !outbound.offer(line)) disconnect("Control output queue full");
    }

    private void disconnect(String reason) {
        if (closed.compareAndSet(false, true)) {
            synchronized (lifecycle) {
                try { if (socket != null) socket.close(); } catch (IOException ignored) {}
            }
            if (writerThread != null) writerThread.interrupt();
            listener.onDisconnected(reason == null ? "Disconnected" : reason);
        }
    }

    @Override public void close() { disconnect("Disconnected"); }
}
