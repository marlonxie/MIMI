import AppKit
import WebKit

/// HTML → PDF 桥：用 WKWebView 渲染 HTML，再调 `WKWebView.pdf(configuration:)` 导出。
/// 等待加载完成走 `WKNavigationDelegate.webView(_:didFinish:)` + `CheckedContinuation`，
/// 不用基于时间的 sleep，确保渲染完整再 snapshot。
@MainActor
final class PDFExporter: NSObject, WKNavigationDelegate {
    private var continuation: CheckedContinuation<Void, Error>?
    private let webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 612, height: 792)) // US Letter

    override init() {
        super.init()
        webView.navigationDelegate = self
    }

    func export(html: String, to url: URL) async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            self.continuation = cont
            webView.loadHTMLString(html, baseURL: nil)
        }
        // rect = nil 时 WebKit 用 CSS @page 自动分页输出多页 PDF。
        // 设了 rect 会被理解成单页快照，多余内容被截掉（之前的 bug）。
        let cfg = WKPDFConfiguration()
        let data = try await webView.pdf(configuration: cfg)
        try data.write(to: url)
    }

    nonisolated func webView(_ wv: WKWebView, didFinish nav: WKNavigation!) {
        Task { @MainActor in
            self.continuation?.resume()
            self.continuation = nil
        }
    }
    nonisolated func webView(_ wv: WKWebView, didFail nav: WKNavigation!, withError e: Error) {
        Task { @MainActor in
            self.continuation?.resume(throwing: e)
            self.continuation = nil
        }
    }
    nonisolated func webView(
        _ wv: WKWebView, didFailProvisionalNavigation nav: WKNavigation!, withError e: Error
    ) {
        Task { @MainActor in
            self.continuation?.resume(throwing: e)
            self.continuation = nil
        }
    }
}
