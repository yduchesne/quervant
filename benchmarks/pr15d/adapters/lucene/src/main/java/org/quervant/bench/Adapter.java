package org.quervant.bench;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Stream;

import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.core.KeywordAnalyzer;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.Field;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.StoredField;
import org.apache.lucene.document.StringField;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.IndexWriter;
import org.apache.lucene.index.IndexWriterConfig;
import org.apache.lucene.index.Term;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.Sort;
import org.apache.lucene.search.SortField;
import org.apache.lucene.search.TermQuery;
import org.apache.lucene.search.TopFieldDocs;
import org.apache.lucene.store.Directory;
import org.apache.lucene.store.FSDirectory;
import org.apache.lucene.util.BytesRef;

/**
 * PR15D benchmark-only Apache Lucene adapter.
 *
 * <p>Uses public Lucene APIs only: {@link FSDirectory}, {@link IndexWriter},
 * {@link DirectoryReader}, {@link IndexSearcher}, {@link TermQuery} and a
 * deterministic {@code doc_id} ascending {@link Sort}. Total hits come from an
 * explicit exact {@code searcher.count(query)} rather than a lower-bounded
 * collector threshold. JSON transport is outside {@code engine_ns}.
 */
public final class Adapter {
    private static final String SCHEMA = "pr15d-adapter-v1";
    private static final String ENGINE = "lucene";
    private static final String ENGINE_VERSION = "Apache Lucene 9.12.3";
    private static final String ADAPTER_VERSION = "0.1.0";
    private static final String ANALYZER = "keyword-exact";
    private static final String HEADER = "doc_id\tkey\tgroup\tbody\tpayload";

    private final Analyzer analyzer = new KeywordAnalyzer();
    private Directory directory;
    private DirectoryReader reader;
    private IndexSearcher searcher;

    public static void main(String[] args) {
        String indexPath = null;
        for (int i = 0; i < args.length; i++) {
            if ("--index-dir".equals(args[i]) && i + 1 < args.length) {
                indexPath = args[++i];
            } else {
                System.err.println("pr15d-lucene-adapter: unknown argument " + args[i]);
                System.exit(2);
            }
        }
        int status = new Adapter().run(indexPath);
        System.exit(status);
    }

    private int run(String indexPath) {
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        BufferedReader in =
                new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String activeIndex = indexPath;
        try {
            String line;
            while ((line = in.readLine()) != null) {
                if (line.trim().isEmpty()) {
                    continue;
                }
                String requestId = "";
                Map<String, Object> body = new LinkedHashMap<>();
                String status = "ok";
                try {
                    Map<String, Object> request = Json.parseObject(line);
                    requestId = Json.string(request.get("request_id"));
                    String op = Json.string(request.get("op"));
                    if ("build".equals(op)) {
                        activeIndex = Json.string(request.get("index_dir"));
                        body = build(Json.string(request.get("corpus_path")), activeIndex);
                    } else if ("query".equals(op)) {
                        if (reader == null) {
                            open(activeIndex);
                        }
                        body = query(request);
                    } else if ("metadata".equals(op)) {
                        body.put("engine_version", ENGINE_VERSION);
                        body.put("adapter_version", ADAPTER_VERSION);
                        body.put("analyzer", ANALYZER);
                        body.put("index_backend", "FSDirectory");
                    } else if ("shutdown".equals(op)) {
                        out.println(reply(requestId, "ok", body));
                        close();
                        return 0;
                    } else {
                        throw new AdapterException("request", "unknown op: " + op);
                    }
                } catch (AdapterException error) {
                    status = "error";
                    Map<String, Object> detail = new LinkedHashMap<>();
                    detail.put("kind", error.kind);
                    detail.put("message", error.getMessage());
                    body = new LinkedHashMap<>();
                    body.put("error", detail);
                } catch (RuntimeException error) {
                    status = "error";
                    Map<String, Object> detail = new LinkedHashMap<>();
                    detail.put("kind", "protocol");
                    detail.put("message", error.toString());
                    body = new LinkedHashMap<>();
                    body.put("error", detail);
                } catch (IOException error) {
                    status = "error";
                    Map<String, Object> detail = new LinkedHashMap<>();
                    detail.put("kind", "io");
                    detail.put("message", error.toString());
                    body = new LinkedHashMap<>();
                    body.put("error", detail);
                }
                out.println(reply(requestId, status, body));
                if ("error".equals(status)) {
                    close();
                    return 1;
                }
            }
            close();
            return 0;
        } catch (IOException error) {
            System.err.println("pr15d-lucene-adapter: " + error);
            return 2;
        }
    }

    private void open(String indexPath) throws IOException {
        if (indexPath == null) {
            throw new AdapterException("request", "query mode requires --index-dir");
        }
        directory = FSDirectory.open(Path.of(indexPath));
        reader = DirectoryReader.open(directory);
        searcher = new IndexSearcher(reader);
    }

    private void close() {
        try {
            if (reader != null) {
                reader.close();
            }
        } catch (IOException ignored) {
            // Best-effort shutdown; a failing close is reported by the process exit path.
        }
        try {
            if (directory != null) {
                directory.close();
            }
        } catch (IOException ignored) {
            // See above.
        }
        reader = null;
        directory = null;
        searcher = null;
    }

    private Map<String, Object> build(String corpusPath, String indexDir) throws IOException {
        List<Document> documents = parseCorpus(corpusPath);
        int expected = documents.size();
        if (indexDir == null) {
            throw new AdapterException("request", "build requires index_dir");
        }
        Path indexPath = Path.of(indexDir);
        Files.createDirectories(indexPath);
        Map<String, Object> result = new LinkedHashMap<>();
        long indexNs;
        long commitNs;
        long reopenNs;
        int verified;
        int segments;
        try (Directory buildDirectory = FSDirectory.open(indexPath)) {
            IndexWriterConfig config = new IndexWriterConfig(analyzer);
            config.setOpenMode(IndexWriterConfig.OpenMode.CREATE);
            try (IndexWriter writer = new IndexWriter(buildDirectory, config)) {
                long started = System.nanoTime();
                for (Document document : documents) {
                    writer.addDocument(document);
                }
                indexNs = System.nanoTime() - started;
                started = System.nanoTime();
                writer.commit();
                commitNs = System.nanoTime() - started;
            }
            long started = System.nanoTime();
            try (DirectoryReader verification = DirectoryReader.open(buildDirectory)) {
                verified = verification.numDocs();
                segments = verification.leaves().size();
            }
            reopenNs = System.nanoTime() - started;
        }
        if (verified != expected) {
            throw new AdapterException(
                    "verification", "reopened " + verified + " documents, expected " + expected);
        }
        result.put("documents_indexed", expected);
        result.put("documents_verified", verified);
        result.put("index_ns", positive(indexNs, "index_ns"));
        result.put("commit_ns", positive(commitNs, "commit_ns"));
        result.put("reopen_ns", positive(reopenNs, "reopen_ns"));
        result.put("index_bytes", directoryBytes(indexPath));
        result.put("segment_count", segments);
        return result;
    }

    private Map<String, Object> query(Map<String, Object> request) throws IOException {
        String field = Json.string(request.get("field"));
        String term = Json.string(request.get("term"));
        int k = Json.integer(request.get("k"));
        if (!"key".equals(field) && !"group".equals(field)) {
            throw new AdapterException("request", "mandatory lane only searches key/group");
        }
        if (k <= 0) {
            throw new AdapterException("request", "k must be positive");
        }
        TermQuery query = new TermQuery(new Term(field, term));
        Sort sort = new Sort(new SortField("doc_id", SortField.Type.STRING));
        long started = System.nanoTime();
        int totalHits = searcher.count(query);
        TopFieldDocs top = searcher.search(query, k, sort);
        long engineNs = System.nanoTime() - started;
        List<String> docIds = new ArrayList<>();
        for (ScoreDoc scoreDoc : top.scoreDocs) {
            Document stored = searcher.storedFields().document(scoreDoc.doc);
            String docId = stored.get("doc_id");
            if (docId == null) {
                throw new AdapterException("projection", "hit is missing stored doc_id");
            }
            docIds.add(docId);
        }
        if (docIds.size() != Math.min(k, totalHits)) {
            throw new AdapterException(
                    "count",
                    "returned " + docIds.size() + " hits for k=" + k + ", total=" + totalHits);
        }
        for (int i = 1; i < docIds.size(); i++) {
            if (docIds.get(i - 1).compareTo(docIds.get(i)) >= 0) {
                throw new AdapterException("ordering", "doc_ids are not ascending");
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("doc_ids", docIds);
        result.put("total_hits", (long) totalHits);
        result.put("engine_ns", positive(engineNs, "engine_ns"));
        return result;
    }

    private static long positive(long value, String field) {
        if (value <= 0) {
            throw new AdapterException(
                    "duration", field + " is not a positive integer nanosecond count");
        }
        return value;
    }

    private static List<Document> parseCorpus(String corpusPath) throws IOException {
        if (corpusPath == null) {
            throw new AdapterException("request", "build requires corpus_path");
        }
        List<String> lines = Files.readAllLines(Path.of(corpusPath), StandardCharsets.UTF_8);
        if (lines.isEmpty() || !HEADER.equals(lines.get(0))) {
            throw new AdapterException("corpus_header", "unexpected TSV header");
        }
        List<Document> documents = new ArrayList<>();
        String previous = null;
        for (int index = 1; index < lines.size(); index++) {
            String line = lines.get(index);
            if (line.isEmpty()) {
                continue;
            }
            String[] columns = line.split("\t", -1);
            if (columns.length != 5) {
                throw new AdapterException(
                        "corpus_row", "line " + (index + 1) + ": expected 5 columns");
            }
            String docId = columns[0];
            if (previous != null && docId.compareTo(previous) <= 0) {
                throw new AdapterException(
                        "corpus_order", "line " + (index + 1) + ": doc_id not increasing");
            }
            previous = docId;
            Document document = new Document();
            addExact(document, "doc_id", columns[0], true);
            addExact(document, "key", columns[1], false);
            addExact(document, "group", columns[2], false);
            document.add(new StoredField("body", columns[3]));
            document.add(new StoredField("payload", columns[4]));
            documents.add(document);
        }
        return documents;
    }

    private static void addExact(Document document, String name, String value, boolean sortable) {
        document.add(new StringField(name, value, Field.Store.YES));
        if (sortable) {
            document.add(new SortedDocValuesField(name, new BytesRef(value)));
        }
    }

    private static long directoryBytes(Path path) throws IOException {
        try (Stream<Path> stream = Files.walk(path)) {
            long total = 0;
            for (Path candidate : (Iterable<Path>) stream::iterator) {
                if (Files.isRegularFile(candidate) && !Files.isSymbolicLink(candidate)) {
                    total += Files.size(candidate);
                }
            }
            return total;
        }
    }

    private static String reply(String requestId, String status, Map<String, Object> body) {
        Map<String, Object> response = new TreeMap<>();
        response.put("schema", SCHEMA);
        response.put("engine", ENGINE);
        response.put("request_id", requestId);
        response.put("status", status);
        response.putAll(body);
        return Json.write(response);
    }

    private static final class AdapterException extends RuntimeException {
        private final String kind;

        AdapterException(String kind, String message) {
            super(message);
            this.kind = kind;
        }
    }

    /** Strict, minimal JSON parser/writer for the flat pr15d request/response shape. */
    private static final class Json {
        static Map<String, Object> parseObject(String text) {
            Parser parser = new Parser(text);
            Map<String, Object> value = parser.object();
            parser.end();
            return value;
        }

        static String string(Object value) {
            if (value == null) {
                return null;
            }
            if (!(value instanceof String)) {
                throw new IllegalArgumentException("expected a JSON string");
            }
            return (String) value;
        }

        static int integer(Object value) {
            if (!(value instanceof Long)) {
                throw new IllegalArgumentException("expected a JSON integer");
            }
            long number = (Long) value;
            if (number < Integer.MIN_VALUE || number > Integer.MAX_VALUE) {
                throw new IllegalArgumentException("integer out of range");
            }
            return (int) number;
        }

        static String write(Object value) {
            StringBuilder builder = new StringBuilder();
            writeValue(builder, value);
            return builder.toString();
        }

        @SuppressWarnings("unchecked")
        private static void writeValue(StringBuilder builder, Object value) {
            if (value == null) {
                builder.append("null");
            } else if (value instanceof String) {
                writeString(builder, (String) value);
            } else if (value instanceof Long || value instanceof Integer) {
                builder.append(value);
            } else if (value instanceof Boolean) {
                builder.append(value);
            } else if (value instanceof Map) {
                builder.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                    if (!first) {
                        builder.append(',');
                    }
                    first = false;
                    writeString(builder, entry.getKey());
                    builder.append(':');
                    writeValue(builder, entry.getValue());
                }
                builder.append('}');
            } else if (value instanceof List) {
                builder.append('[');
                boolean first = true;
                for (Object element : (List<Object>) value) {
                    if (!first) {
                        builder.append(',');
                    }
                    first = false;
                    writeValue(builder, element);
                }
                builder.append(']');
            } else {
                throw new IllegalArgumentException("unsupported JSON value");
            }
        }

        private static void writeString(StringBuilder builder, String value) {
            builder.append('"');
            for (int index = 0; index < value.length(); index++) {
                char ch = value.charAt(index);
                switch (ch) {
                    case '"':
                        builder.append("\\\"");
                        break;
                    case '\\':
                        builder.append("\\\\");
                        break;
                    case '\n':
                        builder.append("\\n");
                        break;
                    case '\r':
                        builder.append("\\r");
                        break;
                    case '\t':
                        builder.append("\\t");
                        break;
                    default:
                        if (ch < 0x20) {
                            builder.append(String.format("\\u%04x", (int) ch));
                        } else {
                            builder.append(ch);
                        }
                }
            }
            builder.append('"');
        }

        private static final class Parser {
            private final String text;
            private int position;

            Parser(String text) {
                this.text = text;
                this.position = 0;
            }

            Map<String, Object> object() {
                Map<String, Object> result = new LinkedHashMap<>();
                skipWhitespace();
                expect('{');
                skipWhitespace();
                if (peek() == '}') {
                    position++;
                    return result;
                }
                while (true) {
                    skipWhitespace();
                    String key = stringLiteral();
                    skipWhitespace();
                    expect(':');
                    skipWhitespace();
                    Object value = value();
                    if (result.put(key, value) != null) {
                        throw new IllegalArgumentException("duplicate JSON key: " + key);
                    }
                    skipWhitespace();
                    char next = peek();
                    if (next == ',') {
                        position++;
                        continue;
                    }
                    expect('}');
                    return result;
                }
            }

            private Object value() {
                char next = peek();
                if (next == '"') {
                    return stringLiteral();
                }
                if (next == '-' || (next >= '0' && next <= '9')) {
                    int start = position;
                    if (next == '-') {
                        position++;
                    }
                    while (position < text.length() && Character.isDigit(text.charAt(position))) {
                        position++;
                    }
                    return Long.parseLong(text.substring(start, position));
                }
                if (text.startsWith("true", position)) {
                    position += 4;
                    return Boolean.TRUE;
                }
                if (text.startsWith("false", position)) {
                    position += 5;
                    return Boolean.FALSE;
                }
                throw new IllegalArgumentException("unsupported JSON value at " + position);
            }

            private String stringLiteral() {
                expect('"');
                StringBuilder builder = new StringBuilder();
                while (true) {
                    if (position >= text.length()) {
                        throw new IllegalArgumentException("unterminated JSON string");
                    }
                    char ch = text.charAt(position++);
                    if (ch == '"') {
                        return builder.toString();
                    }
                    if (ch != '\\') {
                        builder.append(ch);
                        continue;
                    }
                    char escape = text.charAt(position++);
                    switch (escape) {
                        case '"':
                            builder.append('"');
                            break;
                        case '\\':
                            builder.append('\\');
                            break;
                        case '/':
                            builder.append('/');
                            break;
                        case 'b':
                            builder.append('\b');
                            break;
                        case 'f':
                            builder.append('\f');
                            break;
                        case 'n':
                            builder.append('\n');
                            break;
                        case 'r':
                            builder.append('\r');
                            break;
                        case 't':
                            builder.append('\t');
                            break;
                        case 'u':
                            String hex = text.substring(position, position + 4);
                            position += 4;
                            builder.append((char) Integer.parseInt(hex, 16));
                            break;
                        default:
                            throw new IllegalArgumentException("invalid JSON escape");
                    }
                }
            }

            private void skipWhitespace() {
                while (position < text.length()
                        && (text.charAt(position) == ' '
                                || text.charAt(position) == '\t'
                                || text.charAt(position) == '\n'
                                || text.charAt(position) == '\r')) {
                    position++;
                }
            }

            private char peek() {
                if (position >= text.length()) {
                    throw new IllegalArgumentException("unexpected end of JSON");
                }
                return text.charAt(position);
            }

            private void expect(char expected) {
                if (peek() != expected) {
                    throw new IllegalArgumentException(
                            "expected " + expected + " at " + position);
                }
                position++;
            }

            void end() {
                skipWhitespace();
                if (position != text.length()) {
                    throw new IllegalArgumentException("trailing JSON data");
                }
            }
        }
    }
}
