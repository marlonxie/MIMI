import SwiftUI

struct OverlayWindowContent: View {
    let translations: [TranslationEntry]
    let suggestion: String?

    var body: some View {
        VStack(spacing: 0) {
            // 翻译区
            translationSection

            Divider()
                .background(Color.white.opacity(0.3))

            // 提示区
            suggestionSection
        }
        .frame(minWidth: 500, maxWidth: 500, minHeight: 300, maxHeight: 600)
        .background(Color.black.opacity(0.85))
        .cornerRadius(12)
    }

    // MARK: - 翻译区

    private var translationSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("翻译")
                    .font(.caption)
                    .foregroundColor(.gray)
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 6) {
                        ForEach(translations) { entry in
                            TranslationRow(entry: entry)
                                .id(entry.id)
                        }
                    }
                    .padding(.horizontal, 12)
                }
                .onChange(of: translations.count) {
                    if let last = translations.last {
                        withAnimation {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .frame(minHeight: 150)
    }

    // MARK: - 提示区

    private var suggestionSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("回答提示")
                    .font(.caption)
                    .foregroundColor(.orange)
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollView {
                if let suggestion {
                    Text(suggestion)
                        .font(.system(size: 13))
                        .foregroundColor(.white)
                        .textSelection(.enabled)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                } else {
                    Text("等待面试官提问...")
                        .font(.system(size: 13))
                        .foregroundColor(.gray)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                }
            }
        }
        .frame(minHeight: 100)
    }
}

// MARK: - Translation Row

struct TranslationRow: View {
    let entry: TranslationEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Text(entry.speakerLabel)
                    .font(.caption2)
                    .foregroundColor(entry.speaker == "interviewer" ? .cyan : .green)
                    .fontWeight(.bold)
                Text(entry.timestamp)
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
            Text(entry.original)
                .font(.system(size: 13))
                .foregroundColor(.white.opacity(0.9))
            Text(entry.translation)
                .font(.system(size: 13))
                .foregroundColor(.yellow.opacity(0.9))
        }
    }
}
