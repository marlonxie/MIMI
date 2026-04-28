import Security
import Foundation

/// macOS Keychain 包装：以 (service="com.mimi.apikeys", account=key) 存取字符串。
///
/// 用 `Security.framework` 直接调，不引入 SPM 依赖。每个 provider 用 provider 名字作 key
/// （"gemini" / "claude"），存对应的 API 密钥。
enum Keychain {
    private static let service = "com.mimi.apikeys"

    /// 保存。已存在时先删后插（避免 update / insert 分支判断）。
    @discardableResult
    static func save(key: String, value: String) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }
        let baseQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(baseQuery as CFDictionary)
        var addQuery = baseQuery
        addQuery[kSecValueData as String] = data
        let status = SecItemAdd(addQuery as CFDictionary, nil)
        return status == errSecSuccess
    }

    /// 读取。不存在 / 解码失败返回 nil。
    static func load(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess,
              let data = result as? Data,
              let str = String(data: data, encoding: .utf8) else {
            return nil
        }
        return str
    }

    /// 删除（暂不暴露给 UI；保留供未来"清除 key"按钮使用）。
    @discardableResult
    static func delete(key: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        let status = SecItemDelete(query as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
}
