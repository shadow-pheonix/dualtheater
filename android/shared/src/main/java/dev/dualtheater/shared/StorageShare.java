package dev.dualtheater.shared;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.AssetFileDescriptor;
import android.database.Cursor;
import android.net.Uri;
import android.os.CancellationSignal;
import android.provider.DocumentsContract;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** Foreground-only original-byte sharing scoped to one explicit document-tree grant.
 * No public paths/URIs, arbitrary URL fetching, video conversion or whole-file copies.
 */
public final class StorageShare implements AutoCloseable {
    private static final int PAGE = 100, MAX_NODES = 10000;
    private final Context context;
    private final SharedPreferences prefs;
    private final Map<String, Node> nodes = new HashMap<>();
    private final Map<String, Map<String, String>> ids = new HashMap<>();
    private final Map<String, String> parents = new HashMap<>();
    private final ConcurrentMap<Socket, RequestState> requests = new ConcurrentHashMap<>();
    private volatile ServerSocket server;
    private ThreadPoolExecutor workers;
    private ScheduledExecutorService watchdog;
    private long generation;
    private Uri tree;
    private String token = "";
    private static final long IDLE_TIMEOUT_MS = 20_000;

    private static final class RequestState {
        final Socket socket;
        final long acceptedAtNs = System.nanoTime();
        final AtomicLong lastActivityMs = new AtomicLong(System.nanoTime() / 1_000_000L);
        final Set<CancellationSignal> signals = ConcurrentHashMap.newKeySet();
        final Set<AssetFileDescriptor> assets = ConcurrentHashMap.newKeySet();
        volatile boolean cancelled;
        RequestState(Socket socket) { this.socket = socket; }
        void touch() { lastActivityMs.set(System.nanoTime() / 1_000_000L); }
        void cancel() {
            cancelled = true;
            // Resolver/provider cancellation is best effort; closing descriptors and
            // the socket also breaks local I/O, but a provider may ignore both promptly.
            for (CancellationSignal signal : signals) try { signal.cancel(); } catch (RuntimeException ignored) {}
            for (AssetFileDescriptor asset : assets) try { asset.close(); } catch (Exception ignored) {}
            try { socket.close(); } catch (IOException ignored) {}
        }
    }

    private static final class Node {
        final String document, name;
        final boolean directory;
        final long size, assetSize, modified;
        Node(String document, String name, boolean directory, long size, long modified) {
            this(document, name, directory, size, -1, modified);
        }
        Node(String document, String name, boolean directory, long size, long assetSize, long modified) {
            this.document = document; this.name = name; this.directory = directory;
            this.size = size; this.assetSize = assetSize; this.modified = modified;
        }
    }

    public StorageShare(Context context) {
        this.context = context.getApplicationContext();
        prefs = this.context.getSharedPreferences("dualtheater_storage_share", Context.MODE_PRIVATE);
        String saved = prefs.getString("tree", "");
        if (!saved.isEmpty()) tree = Uri.parse(saved);
    }

    public static Intent pickerIntent() {
        return new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
    }

    private boolean hasReadGrant(Uri value) {
        if (value == null) return false;
        for (android.content.UriPermission permission : context.getContentResolver().getPersistedUriPermissions())
            if (permission.isReadPermission() && permission.getUri().equals(value)) return true;
        return context.checkUriPermission(value, android.os.Process.myPid(), android.os.Process.myUid(),
            Intent.FLAG_GRANT_READ_URI_PERMISSION) == PackageManager.PERMISSION_GRANTED;
    }

    public synchronized boolean hasTree() {
        return tree != null && "content".equals(tree.getScheme()) && DocumentsContract.isTreeUri(tree) && hasReadGrant(tree);
    }

    public synchronized void setTree(Uri value) {
        if (value == null || !"content".equals(value.getScheme()) || !DocumentsContract.isTreeUri(value))
            throw new IllegalArgumentException("Choose a folder with the system picker");
        if (!hasReadGrant(value)) throw new IllegalArgumentException("Folder read permission is unavailable; choose it again");
        Uri previous = tree;
        close();
        tree = value;
        prefs.edit().putString("tree", value.toString()).apply();
        if (previous != null && !previous.equals(value)) releaseTreeGrant(previous);
    }

    private void releaseTreeGrant(Uri value) {
        try { context.getContentResolver().releasePersistableUriPermission(value, Intent.FLAG_GRANT_READ_URI_PERMISSION); }
        catch (SecurityException ignored) {}
    }

    public synchronized void forgetTree() {
        Uri previous = tree;
        close(); tree = null; prefs.edit().remove("tree").apply();
        if (previous != null) releaseTreeGrant(previous);
    }

    public synchronized JSONObject start() throws Exception {
        if (tree == null) throw new IOException("Choose a storage folder first");
        if (!"content".equals(tree.getScheme()) || !DocumentsContract.isTreeUri(tree) || !hasReadGrant(tree))
            throw new IOException("Folder read permission expired; choose the folder again");
        if (server == null || server.isClosed()) {
            nodes.clear(); ids.clear(); parents.clear();
            token = UUID.randomUUID().toString().replace("-", "") + UUID.randomUUID().toString().replace("-", "");
            ServerSocket listener = new ServerSocket(0, 8);
            server = listener;
            long listenerGeneration = ++generation;
            ThreadPoolExecutor listenerWorkers = new ThreadPoolExecutor(4, 4, 30, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(8), task -> { Thread t = new Thread(task, "DualTheater-storage"); t.setDaemon(true); return t; });
            workers = listenerWorkers;
            ScheduledExecutorService listenerWatchdog = Executors.newSingleThreadScheduledExecutor(task -> {
                Thread t = new Thread(task, "DualTheater-storage-watchdog"); t.setDaemon(true); return t;
            });
            watchdog = listenerWatchdog;
            listenerWatchdog.scheduleAtFixedRate(() -> expireIdle(listener, listenerGeneration),
                2, 2, TimeUnit.SECONDS);
            new Thread(() -> {
                while (isCurrent(listener, listenerGeneration) && !listener.isClosed()) {
                    try {
                        Socket client = listener.accept();
                        try { client.setSoTimeout(10000); }
                        catch (IOException error) { try { client.close(); } catch (IOException ignored) {} throw error; }
                        adopt(listener, listenerWorkers, listenerGeneration, client);
                    } catch (IOException error) {
                        if (isCurrent(listener, listenerGeneration)) StorageShare.this.close();
                        break;
                    }
                }
            }, "DualTheater-storage-listener").start();
        }
        return new JSONObject().put("op", "storage_register").put("port", server.getLocalPort())
            .put("token", token).put("label", "Android storage");
    }

    private synchronized boolean isCurrent(ServerSocket listener, long expectedGeneration) {
        return server == listener && generation == expectedGeneration && !listener.isClosed();
    }

    private void adopt(ServerSocket listener, ThreadPoolExecutor executor, long expectedGeneration, Socket client) {
        synchronized (this) {
            if (server != listener || workers != executor || generation != expectedGeneration || listener.isClosed()) {
                try { client.close(); } catch (IOException ignored) {}
                return;
            }
            RequestState request = new RequestState(client);
            requests.put(client, request);
            try { executor.execute(() -> serve(request, listener, expectedGeneration)); }
            catch (RuntimeException error) {
                requests.remove(client); request.cancel();
            }
        }
    }

    private void expireIdle(ServerSocket listener, long expectedGeneration) {
        if (!isCurrent(listener, expectedGeneration)) return;
        long now = System.nanoTime() / 1_000_000L;
        for (RequestState request : requests.values())
            if (now - request.lastActivityMs.get() > IDLE_TIMEOUT_MS) request.cancel();
    }

    private synchronized Node node(String id) throws IOException {
        if (tree == null) throw new IOException("Folder is no longer shared");
        if (id.isEmpty()) return new Node(DocumentsContract.getTreeDocumentId(tree), "Shared folder", true, 0, 0);
        Node node = nodes.get(id);
        if (node == null) throw new IOException("Folder listing expired; browse again");
        return node;
    }

    private synchronized String idFor(Node node, String parent) throws IOException {
        Map<String, String> siblings = ids.computeIfAbsent(parent, ignored -> new HashMap<>());
        String value = siblings.get(node.document);
        if (value == null) {
            if (nodes.size() >= MAX_NODES) throw new IOException("Too many entries; choose a smaller shared folder");
            value = UUID.randomUUID().toString().replace("-", ""); siblings.put(node.document, value);
        }
        nodes.put(value, node); parents.put(value, parent); return value;
    }

    private synchronized Uri uri(Node node) { return DocumentsContract.buildDocumentUriUsingTree(tree, node.document); }

    private CancellationSignal beginProviderCall(RequestState request) throws IOException {
        if (request.cancelled) throw new IOException("Request cancelled");
        CancellationSignal signal = new CancellationSignal();
        request.signals.add(signal);
        if (request.cancelled) {
            request.signals.remove(signal); signal.cancel();
            throw new IOException("Request cancelled");
        }
        return signal;
    }

    private AssetFileDescriptor openAsset(Node node, RequestState request) throws IOException {
        CancellationSignal signal = beginProviderCall(request);
        AssetFileDescriptor asset;
        try { asset = context.getContentResolver().openAssetFileDescriptor(uri(node), "r", signal); }
        finally { request.signals.remove(signal); }
        if (asset == null) throw new IOException("File is unavailable");
        request.assets.add(asset);
        if (request.cancelled) {
            request.assets.remove(asset); asset.close();
            throw new IOException("Request cancelled");
        }
        request.touch();
        return asset;
    }

    private void closeAsset(AssetFileDescriptor asset, RequestState request) {
        request.assets.remove(asset);
        try { asset.close(); } catch (IOException ignored) {}
    }

    private JSONObject browse(String entry, int cursor, RequestState request) throws Exception {
        if (cursor < 0 || cursor > MAX_NODES) throw new IOException("Invalid page");
        Node parent = node(entry);
        if (!parent.directory) throw new IOException("Choose a folder");
        Uri children;
        synchronized (this) { children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parent.document); }
        String[] projection = {DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED};
        List<Node> rows = new ArrayList<>();
        CancellationSignal signal = beginProviderCall(request);
        try (Cursor query = context.getContentResolver().query(children, projection, null, null, null, signal)) {
            if (query == null) throw new IOException("Cannot read folder; choose it again");
            while (query.moveToNext()) {
                String name = query.getString(1), mime = query.getString(2);
                boolean directory = DocumentsContract.Document.MIME_TYPE_DIR.equals(mime);
                if (name == null || name.length() > 512 || (!directory && !movie(name))) continue;
                rows.add(new Node(query.getString(0), name, directory, query.isNull(3) ? -1 : query.getLong(3), query.isNull(4) ? 0 : query.getLong(4)));
                if (rows.size() > MAX_NODES) throw new IOException("Folder too large; share a smaller folder");
                request.touch();
            }
        } finally { request.signals.remove(signal); }
        if (request.cancelled) throw new IOException("Request cancelled");
        rows.sort(Comparator.comparing((Node n) -> !n.directory).thenComparing(n -> n.name.toLowerCase(Locale.ROOT)).thenComparing(n -> n.name));
        if (cursor > rows.size()) throw new IOException("Folder changed; refresh the listing");
        JSONArray entries = new JSONArray();
        int end = Math.min(rows.size(), cursor + PAGE);
        for (Node row : rows.subList(cursor, end)) {
            if (request.cancelled) throw new IOException("Request cancelled");
            Node n = row;
            long size = n.directory ? 0 : seekableSize(n, request);
            if (!n.directory) n = new Node(n.document, n.name, false, n.size, size, n.modified);
            String id = idFor(n, entry);
            JSONObject record = new JSONObject().put("id", id).put("name", n.name).put("directory", n.directory);
            if (!n.directory) record.put("size", Math.max(0, size)).put("seekable", size > 0);
            entries.put(record);
        }
        String parentId;
        synchronized (this) { parentId = parents.getOrDefault(entry, ""); }
        return new JSONObject().put("provider", "android").put("entry", entry).put("parent", parentId)
            .put("label", parent.name).put("entries", entries).put("next_cursor", end < rows.size() ? end : JSONObject.NULL);
    }

    private static boolean movie(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        return lower.endsWith(".mkv") || lower.endsWith(".mp4") || lower.endsWith(".m2ts") || lower.endsWith(".ts");
    }

    private long seekableSize(Node node, RequestState request) {
        AssetFileDescriptor asset = null;
        try {
            asset = openAsset(node, request);
            long size = asset.getLength();
            if (size < 0) size = asset.getParcelFileDescriptor().getStatSize() - asset.getStartOffset();
            if (size <= 0) return -1;
            long last = Math.addExact(asset.getStartOffset(), size - 1);
            Os.lseek(asset.getFileDescriptor(), last, OsConstants.SEEK_SET);
            Os.lseek(asset.getFileDescriptor(), asset.getStartOffset(), OsConstants.SEEK_SET);
            return size;
        } catch (Exception error) { return -1; }
        finally { if (asset != null) closeAsset(asset, request); }
    }

    private Node currentMetadata(Node item, RequestState request) throws IOException {
        Uri document = uri(item);
        String[] projection = {DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED};
        CancellationSignal signal = beginProviderCall(request);
        try (Cursor query = context.getContentResolver().query(document, projection, null, null, null, signal)) {
            if (query == null || !query.moveToFirst()) throw new IOException("Document metadata unavailable");
            request.touch();
            return new Node(item.document, query.getString(0), false,
                query.isNull(1) ? -1 : query.getLong(1),
                query.isNull(2) ? 0 : query.getLong(2));
        } finally { request.signals.remove(signal); }
    }

    private void validateSnapshot(Node item, long openedSize, RequestState request) throws IOException {
        if (openedSize <= 0 || (item.assetSize > 0 && openedSize != item.assetSize))
            throw new IOException("File changed or is not seekable");
        Node current = currentMetadata(item, request);
        if (!item.name.equals(current.name)
                || item.size > 0 && current.size != item.size
                || item.modified > 0 && current.modified != item.modified)
            throw new IOException("File changed; browse again");
    }

    private void serve(RequestState request, ServerSocket listener, long expectedGeneration) {
        Socket client = request.socket;
        boolean headersSent = false;
        boolean head = false;
        try {
            Socket socket = client;
            InputStream input = socket.getInputStream(); OutputStream output = socket.getOutputStream();
            String requestLine = line(input, 4096, request);
            String[] first = requestLine.split(" ", -1);
            if (first.length != 3 || (!first[0].equals("GET") && !first[0].equals("HEAD"))) {
                headersSent = true;
                reply(output, 405, new JSONObject().put("error", "GET or HEAD required").toString().getBytes(StandardCharsets.UTF_8), false); return;
            }
            head = first[0].equals("HEAD");
            Map<String, String> headers = new HashMap<>(); int budget = 8192;
            while (true) {
                String header = line(input, Math.min(4096, budget), request); budget -= header.length() + 2;
                if (budget < 0) throw new IOException("Headers too large");
                if (header.isEmpty()) break;
                int colon = header.indexOf(':'); if (colon <= 0) throw new IOException("Invalid header");
                String key = header.substring(0, colon).toLowerCase(Locale.ROOT);
                if (headers.put(key, header.substring(colon + 1).trim()) != null) throw new IOException("Duplicate header");
            }
            URI parsed = new URI(first[1]);
            if (parsed.isAbsolute() || parsed.getRawFragment() != null) throw new IOException("Invalid target");
            String path = parsed.getPath();
            String[] parts = path.split("/", -1);
            String expected;
            synchronized (this) { expected = token; }
            if (parts.length < 3 || expected.isEmpty() || !MessageDigest.isEqual(parts[1].getBytes(StandardCharsets.UTF_8), expected.getBytes(StandardCharsets.UTF_8))) {
                headersSent = true;
                reply(output, 404, new byte[0], head); return;
            }
            if (!hasReadGrant(tree)) {
                headersSent = true;
                byte[] body = "{\"error\":\"Folder read access expired. Choose the folder again.\"}".getBytes(StandardCharsets.UTF_8);
                reply(output, 410, body, head); return;
            }
            if (parts.length == 3 && parts[2].equals("browse")) {
                Map<String, String> query = new HashMap<>();
                if (parsed.getRawQuery() != null) for (String pair : parsed.getRawQuery().split("&")) {
                    String[] pieces = pair.split("=", 2);
                    query.put(URLDecoder.decode(pieces[0], "UTF-8"), pieces.length == 2 ? URLDecoder.decode(pieces[1], "UTF-8") : "");
                }
                byte[] body = browse(query.getOrDefault("entry", ""), Integer.parseInt(query.getOrDefault("cursor", "0")), request)
                    .toString().getBytes(StandardCharsets.UTF_8);
                headersSent = true;
                reply(output, 200, body, head); return;
            }
            if (parts.length != 4 || !parts[2].equals("file") || !parts[3].matches("[a-f0-9]{32}")) {
                headersSent = true;
                reply(output, 404, new byte[0], head); return;
            }
            Node item = node(parts[3]);
            if (item.directory || !movie(item.name)) throw new IOException("Choose a movie");
            AssetFileDescriptor asset = openAsset(item, request);
            try {
                long size = asset.getLength();
                if (size < 0) size = asset.getParcelFileDescriptor().getStatSize() - asset.getStartOffset();
                validateSnapshot(item, size, request);
                ByteRange range;
                try { range = ByteRange.parse(headers.get("range"), size); }
                catch (IllegalArgumentException error) {
                    headersSent = true;
                    byte[] response = ("HTTP/1.1 416 Range Not Satisfiable\r\nContent-Range: bytes */" + size
                        + "\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII);
                    output.write(response); request.touch(); return;
                }
                Os.lseek(asset.getFileDescriptor(), asset.getStartOffset() + range.start, OsConstants.SEEK_SET);
                String response = "HTTP/1.1 " + (range.partial ? "206 Partial Content" : "200 OK")
                    + "\r\nContent-Type: application/octet-stream\r\nAccept-Ranges: bytes\r\nCache-Control: private, no-store, no-transform"
                    + "\r\nContent-Length: " + (range.end - range.start + 1)
                    + (range.partial ? "\r\nContent-Range: bytes " + range.start + "-" + range.end + "/" + size : "")
                    + "\r\nConnection: close\r\n\r\n";
                headersSent = true;
                output.write(response.getBytes(StandardCharsets.US_ASCII)); request.touch();
                if (head) return;
                try (InputStream file = asset.createInputStream()) {
                    // createInputStream may seek back to the asset start.
                    Os.lseek(asset.getFileDescriptor(), asset.getStartOffset() + range.start, OsConstants.SEEK_SET);
                    byte[] buffer = new byte[256 * 1024]; long remaining = range.end - range.start + 1;
                    while (remaining > 0 && isCurrent(listener, expectedGeneration) && !socket.isClosed()) {
                        int count = file.read(buffer, 0, (int)Math.min(buffer.length, remaining));
                        if (count < 0) throw new EOFException("File ended early");
                        if (count == 0) continue;
                        output.write(buffer, 0, count); remaining -= count; request.touch();
                    }
                    if (remaining > 0) throw new IOException("Share stopped");
                }
            } finally { closeAsset(asset, request); }
        } catch (Exception error) {
            // Avoid logging paths, URIs, capabilities or free-form provider errors.
            // A response with incomplete original bytes is closed, never padded.
            if (!headersSent && !client.isClosed()) try {
                headersSent = true;
                reply(client.getOutputStream(), 400, "{\"error\":\"Cannot read this folder/file. Choose a local seekable storage folder and retry.\"}".getBytes(StandardCharsets.UTF_8), head);
            } catch (IOException ignored) {}
        } finally { requests.remove(client); request.cancel(); }
    }

    private static String line(InputStream input, int limit, RequestState request) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        for (int i = 0; i <= limit; i++) {
            if (System.nanoTime() > deadline || System.nanoTime() - request.acceptedAtNs > TimeUnit.SECONDS.toNanos(20)
                    || request.cancelled)
                throw new SocketTimeoutException("Request headers timed out");
            int c = input.read(); if (c == -1) throw new EOFException();
            request.touch();
            if (c == '\n') return bytes.toString("US-ASCII").replace("\r", "");
            if (i == limit) throw new IOException("Line too large"); bytes.write(c);
        }
        throw new IOException("Line too large");
    }

    private static void reply(OutputStream output, int status, byte[] bytes, boolean head) throws IOException {
        output.write(("HTTP/1.1 " + status + " Response\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: "
            + bytes.length + "\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
        if (!head) output.write(bytes);
    }

    @Override public synchronized void close() {
        ++generation;
        ServerSocket listener = server; server = null; token = "";
        ThreadPoolExecutor oldWorkers = workers; workers = null;
        ScheduledExecutorService oldWatchdog = watchdog; watchdog = null;
        try { if (listener != null) listener.close(); } catch (IOException ignored) {}
        for (RequestState request : requests.values()) request.cancel();
        requests.clear();
        if (oldWorkers != null) oldWorkers.shutdownNow();
        if (oldWatchdog != null) oldWatchdog.shutdownNow();
        nodes.clear(); ids.clear(); parents.clear();
    }
}
