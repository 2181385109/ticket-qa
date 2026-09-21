// h2c 升级 + chunked 请求体让 WireMock 丢请求体的最小复现。用法:起 WireMock 后  java ops/smoke/H2cRepro.java
// 背景与结论见 docs/findings/20260920-联调发现-h2c升级导致LLM静默降级.md
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;

public class H2cRepro {
    public static void main(String[] args) throws Exception {
        String body = "{\"title\":\"[BAD_CATEGORY] repro\",\"content\":\"x\"}";
        for (String ver : new String[]{"default", "http1.1"}) {
            for (String pub : new String[]{"ofString", "ofInputStream"}) {
                HttpClient.Builder b = HttpClient.newBuilder();
                if (ver.equals("http1.1")) b.version(HttpClient.Version.HTTP_1_1);
                HttpClient client = b.build();
                for (int i = 1; i <= 2; i++) {
                    HttpRequest.BodyPublisher p = pub.equals("ofString")
                            ? HttpRequest.BodyPublishers.ofString(body)
                            : HttpRequest.BodyPublishers.ofInputStream(
                                    () -> new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8)));
                    HttpRequest req = HttpRequest.newBuilder(URI.create("http://127.0.0.1:8089/mock/llm/classify"))
                            .header("Content-Type", "application/json").POST(p).build();
                    try {
                        HttpResponse<String> r = client.send(req, HttpResponse.BodyHandlers.ofString());
                        System.out.println(ver + "/" + pub + "#" + i + " -> " + r.statusCode() + " " + r.body());
                    } catch (Exception e) {
                        System.out.println(ver + "/" + pub + "#" + i + " -> EXCEPTION " + e);
                    }
                }
            }
        }
    }
}
