// The window's link to portal.py: one long-lived `portal.py serve` process, JSON lines both ways (see serve()).
import Foundation

struct BackendError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

final class Backend: @unchecked Sendable {
    static let shared = Backend()
    private let proc = Process()
    private let input = Pipe(), output = Pipe()
    private let lock = NSLock()  // guards everything below
    private var next = 0
    private var waiting: [Int: CheckedContinuation<Any, Error>] = [:]
    private var buffer = Data()

    private init() {
        signal(SIGPIPE, SIG_IGN)  // a write after the backend died should throw, not kill the app
        let macos = Bundle.main.executableURL!.deletingLastPathComponent()
        let script = Bundle.main.resourceURL!.appendingPathComponent("portal.py")
        if FileManager.default.fileExists(atPath: script.path) {  // `portal.py package`: this Mac's Python and the script
            proc.executableURL = macos.appendingPathComponent("python")
            proc.arguments = [script.path, "serve"]
        } else {  // scripts/build-app.sh: PyInstaller's bundled Python, next to this binary
            proc.executableURL = macos.appendingPathComponent("Windows Portal")
            proc.arguments = ["serve"]
        }
        var env = ProcessInfo.processInfo.environment  // Finder gives apps a bare PATH; add Homebrew's (winetricks, brew)
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
        proc.environment = env
        proc.standardInput = input
        proc.standardOutput = output
        output.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil } else { self?.received(d) }
        }
        // ponytail: no restart; if the backend crashes, calls fail until the app is reopened
        proc.terminationHandler = { [weak self] _ in self?.failAll() }
        do { try proc.run() } catch { NSLog("Windows Portal: backend didn't start: \(error)") }
    }

    private func received(_ d: Data) {
        var done: [(CheckedContinuation<Any, Error>, Result<Any, Error>)] = []
        lock.lock()
        buffer.append(d)
        while let nl = buffer.firstIndex(of: 10) {
            let line = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            guard let r = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let id = r["id"] as? Int,
                  let c = waiting.removeValue(forKey: id) else { continue }
            if let e = r["error"] as? String { done.append((c, .failure(BackendError(message: e)))) }
            else { done.append((c, .success(r["ok"] ?? NSNull()))) }
        }
        lock.unlock()
        for (c, r) in done { c.resume(with: r) }
    }

    private func failAll() {
        lock.lock()
        let all = waiting.values
        waiting = [:]
        lock.unlock()
        for c in all { c.resume(throwing: BackendError(message: "Windows Portal's backend stopped. Reopen the app.")) }
    }

    /// Calls a function serve() exposes; resolves with its JSON result. With a job id it runs in its own worker
    /// process, which call("cancel", [job]) stops.
    func call(_ name: String, _ args: [Any] = [], kw: [String: Any] = [:], job: String? = nil) async throws -> Any {
        try await withCheckedThrowingContinuation { c in
            lock.lock()
            defer { lock.unlock() }
            guard proc.isRunning else {
                return c.resume(throwing: BackendError(message: "Windows Portal's backend isn't running. Reopen the app."))
            }
            next += 1
            waiting[next] = c
            do {
                var req: [String: Any] = ["id": next, "call": name, "args": args, "kw": kw]
                if let job { req["job"] = job }
                var line = try JSONSerialization.data(withJSONObject: req)
                line.append(10)
                try input.fileHandleForWriting.write(contentsOf: line)
            } catch {
                waiting.removeValue(forKey: next)?.resume(throwing: error)
            }
        }
    }

    func get<T: Decodable>(_ type: T.Type, _ name: String, _ args: [Any] = []) async throws -> T {
        let value = try await call(name, args)
        let data = try JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed)
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(T.self, from: data)
    }
}
