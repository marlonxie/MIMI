import SwiftUI

struct SettingsView: View {
    @Bindable var appState: AppState

    var body: some View {
        TabView {
            languageTab
                .tabItem { Label(appState.t("settings.tab.language"), systemImage: "globe") }
                .padding()

            uiTab
                .tabItem { Label(appState.t("settings.tab.ui"), systemImage: "paintbrush") }
                .padding()

            suggestionTab
                .tabItem { Label(appState.t("settings.tab.suggestion"), systemImage: "lightbulb") }
                .padding()

            apiKeyTab
                .tabItem { Label(appState.t("settings.tab.api"), systemImage: "key") }
                .padding()
        }
        .frame(width: 460, height: 320)
    }

    // MARK: - Language tab

    private var languageTab: some View {
        Form {
            Picker(appState.t("settings.interviewLanguage"),
                   selection: $appState.interviewLanguage) {
                Text("English").tag("en")
                Text("Deutsch").tag("de")
            }
            Picker(appState.t("settings.nativeLanguage"),
                   selection: $appState.nativeLanguage) {
                Text("中文").tag("zh")
                Text("English").tag("en")
            }
            Text(appState.t("settings.languageHint"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - UI (interface language) tab

    private var uiTab: some View {
        Form {
            Picker(appState.t("settings.uiLanguage"), selection: $appState.uiLanguage) {
                ForEach(UILang.allCases, id: \.rawValue) { lang in
                    Text(lang.displayName).tag(lang.rawValue)
                }
            }
            Text(appState.t("settings.uiLanguage.hint"))
                .font(.caption)
                .foregroundStyle(.secondary)

            Divider().padding(.vertical, 6)

            Button(appState.t("settings.replayOnboarding")) {
                appState.hasCompletedOnboarding = false
                appState.onboardingStep = 0
                appState.appDelegate?.showOnboarding(appState: appState)
            }
        }
    }

    // MARK: - Suggestion tab

    private var suggestionTab: some View {
        Form {
            Toggle(appState.t("settings.suggestion.toggle"),
                   isOn: $appState.suggestionEnabled)
            Text(appState.t("settings.suggestion.hint"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - API Key tab

    private var apiKeyTab: some View {
        Form {
            Picker(appState.t("settings.api.provider"), selection: $appState.llmProvider) {
                Text("Google Gemini").tag("gemini")
                Text("Anthropic Claude").tag("claude")
                Text(appState.t("settings.api.local")).tag("ollama")
            }
            .onChange(of: appState.llmProvider) { _, _ in
                appState.loadApiKeyForCurrentProvider()
            }

            if appState.llmProvider == "ollama" {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "checkmark.shield").foregroundStyle(.green)
                    Text(appState.t("settings.api.localHint"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Button(appState.t("settings.api.save")) {
                    appState.applyApiKey()
                }
            } else {
                SecureField("API Key",
                            text: $appState.apiKey,
                            prompt: Text(appState.t("settings.api.placeholder")))
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Button(appState.t("settings.api.save")) {
                        appState.applyApiKey()
                    }
                    .disabled(appState.apiKey.isEmpty)

                    Spacer()

                    if appState.translationReady {
                        Label(appState.t("settings.api.translationReady"),
                              systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.caption)
                    }
                }

                if appState.translationReady && appState.apiKey.isEmpty {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "info.circle").foregroundStyle(.blue)
                        Text(appState.t("settings.api.envHint"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Text(appState.t("settings.api.keychainHint"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
