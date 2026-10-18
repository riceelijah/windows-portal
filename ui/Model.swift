// What the window shows, loaded from the backend, and the actions behind its buttons.
import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct Info: Decodable {
    struct Engine: Decodable { let name: String; let installed: Bool; let graphics: [String] }
    let engines: [String: Engine]
    let renderers: [String: String]
    let catalog: [String]
    let archives: [String]
    let d3dmetalAccepted: Bool
    let d3dmetalLicense: String
    let arm64Missing: String?
    let artKey: String
}

struct BottleInfo: Decodable, Hashable { let name, engine, graphics: String }

struct Program: Decodable, Hashable {
    let title, bottle, target: String
    let icon, appid: String?
    let mac: Bool
    var played: Double
}

struct Library: Decodable { let bottles: [BottleInfo]; let items: [Program]; let error: String? }

struct StoreGame: Decodable, Hashable {
    let id, title: String
    let bottle, installed, art: String?
    let mac, macInstalled, windows: Bool?
    let size: Int64?  // Steam's, from the list; other stores' are asked for (ui_game_size)
    var played: Double
}

struct GameSize: Decodable { let bytes: Int64?; let download: Bool }

func bytes(_ n: Int64) -> String { ByteCountFormatter.string(fromByteCount: n, countStyle: .file) }

struct StoreLib: Decodable { let connected: Bool; var games: [StoreGame] }

struct Detail: Decodable {
    let engine, graphics, graphicsName, files: String
    let options: [String]
    let own: [String: String]
    let added: Bool
}

struct Compat: Decodable { let verdict, url: String; let blocked: Bool }

enum Place: Hashable { case all, bottle(String), store(String) }

let storeNames: [(key: String, name: String)] = [("steam", "Steam"), ("epic", "Epic Games"), ("gog", "GOG"),
                                                  ("itch", "itch.io"), ("amazon", "Amazon Games")]
func storeName(_ key: String) -> String { storeNames.first { $0.key == key }?.name ?? key }

/// One library tile: a program in a bottle, or a game a store account owns.
struct Tile: Identifiable {
    let id, title, subtitle: String
    let image: String?
    let program: Program?
    let store: String?
    let game: StoreGame?
    let engine: String  // for the engine filters
    let mac, installed: Bool
    let played: Double
    let size: Int64?
}

/// Something running, shown in the sidebar; a cancellable one runs in its own worker process.
struct Running { let message: String; let cancellable: Bool }

/// An alert waiting for an answer: buttons to pick from, or a text field when `text` is set.
struct Question {
    let title, message: String
    let buttons: [String]
    let cancel: Bool
    let text: String?
    let answer: (String?) -> Void
}

@MainActor @Observable final class Model {
    var info: Info?
    var bottles: [BottleInfo] = []
    var programs: [Program] = []
    var stores: [String: StoreLib] = [:]
    var art: [String: String] = [:]  // tile id -> cover, as covers arrive
    var place: Place? = .all
    var selection: String?
    var tasks: [UUID: Running] = [:]  // what's running, for the sidebar
    var sizes: [String: Int64] = [:]  // tile id -> bytes on disk, as they're measured
    var notice: String?
    var questions: [Question] = []
    var answerText = ""
    var lastRefresh = Date.distantPast
    private var fetched: Set<String> = []  // stores whose live list was asked for since the last Refresh
    private var artAsked: Set<String> = []
    private var sizeAsked: Set<String> = []
    let backend = Backend.shared

    init() { Task { await refresh() } }

    // ---------- loading ----------
    func refresh() async {
        lastRefresh = .now
        let id = begin("Loading library…")
        defer { tasks[id] = nil }
        do {
            async let i = backend.get(Info.self, "ui_info")
            let lib = try await backend.get(Library.self, "ui_library")
            (bottles, programs, notice) = (lib.bottles, lib.items, lib.error)
            info = try await i
        } catch {
            await tell(error.localizedDescription)
        }
        if case .store(let s)? = place, let fresh = try? await backend.get(StoreLib.self, "ui_store", [s, false]) {
            stores[s] = fresh
        }
    }

    /// A store's cached list at once, then the account's current one.
    func openStore(_ s: String, reload: Bool = false) async {
        if reload { fetched.remove(s) }
        guard !fetched.contains(s) else { return }
        fetched.insert(s)
        if stores[s] == nil { stores[s] = try? await backend.get(StoreLib.self, "ui_store", [s, false]) }
        guard s != "steam" || reload else { return }  // Steam's list is read from disk: the cached one is current
        let id = begin("Loading \(storeName(s))…")
        defer { tasks[id] = nil }
        do { stores[s] = try await backend.get(StoreLib.self, "ui_store", [s, true]) }
        catch { notice = "\(storeName(s)): \(error.localizedDescription)" }
    }

    func wantArt(_ t: Tile) {
        guard let s = t.store, let g = t.game, t.image == nil, !artAsked.contains(t.id) else { return }
        artAsked.insert(t.id)
        Task {
            if let path = try? await backend.call("ui_art", [s, g.id, g.title]) as? String { art[t.id] = path }
        }
    }

    /// What a tile takes on disk: library programs and installed store games are measured (du) as they appear.
    func wantSize(_ t: Tile) {
        guard t.size == nil, !sizeAsked.contains(t.id) else { return }
        let call: (String, [Any])
        if let p = t.program { call = ("ui_program_size", [p.bottle, p.target]) }
        else if let s = t.store, let g = t.game, s != "steam", g.installed != nil { call = ("ui_game_size", [s, g.id]) }
        else { return }
        sizeAsked.insert(t.id)
        Task {
            let r = try? await backend.call(call.0, call.1)
            if let n = (r as? NSNumber)?.int64Value ?? ((r as? [String: Any])?["bytes"] as? NSNumber)?.int64Value {
                sizes[t.id] = n
            }
        }
    }

    // ---------- tiles ----------
    var title: String {
        switch place {
        case .bottle(let b)?: b
        case .store(let s)?: storeName(s)
        default: "All Programs"
        }
    }

    var currentBottle: String? {
        if case .bottle(let b)? = place { return b }
        return nil
    }

    func engineName(_ bottle: String) -> String {
        let e = bottles.first { $0.name == bottle }?.engine ?? ""
        return info?.engines[e]?.name ?? e
    }

    var tiles: [Tile] {
        if case .store(let s)? = place {
            return (stores[s]?.games ?? []).map { g in
                let id = "\(s)|\(g.id)"
                return Tile(id: id, title: g.title, subtitle: status(g), image: g.art ?? art[id], program: nil, store: s,
                            game: g, engine: "", mac: g.mac == true, installed: g.installed != nil || g.macInstalled == true,
                            played: g.played, size: g.size ?? sizes[id])
            }
        }
        return programs.filter { currentBottle == nil || $0.bottle == currentBottle }.map { p in
            let id = "\(p.bottle)|\(p.target)"
            return Tile(id: id, title: p.title, subtitle: p.bottle, image: p.icon, program: p, store: nil, game: nil,
                        engine: engineName(p.bottle), mac: p.mac, installed: true, played: p.played, size: sizes[id])
        }
    }

    private func status(_ g: StoreGame) -> String {
        let win = g.installed.map { "Installed in \($0)" } ?? (g.windows ?? true ? "Not installed" : "No Windows version")
        guard g.mac == true else { return win }
        return g.macInstalled == true ? "Mac · installed" : "Mac version · \(win)"
    }

    var isStore: Bool { if case .store? = place { true } else { false } }

    var sorts: [String] { ["Name A–Z", "Name Z–A", "Recently played", "Largest first", isStore ? "Installed first" : "Bottle"] }

    /// Filter checkboxes stack: within a group a tile passes if any ticked box fits it, across groups it must pass each.
    var filterGroups: [[String]] {
        isStore ? [["Has Mac version", "No Mac version"], ["Installed", "Not installed"]]
                : [Array(Set(tiles.map(\.engine))).sorted(), ["Has Mac version", "No Mac version"]]
    }

    func shown(query: String, sort: String, filters: Set<String>) -> [Tile] {
        func fits(_ t: Tile, _ f: String) -> Bool {
            switch f {
            case "Has Mac version": t.mac
            case "No Mac version": !t.mac
            case "Installed": t.installed
            case "Not installed": !t.installed
            default: t.engine == f
            }
        }
        let groups = filterGroups.map { $0.filter(filters.contains) }
        let q = query.lowercased()
        let keep = tiles.filter { t in
            (q.isEmpty || t.title.lowercased().contains(q)) && groups.allSatisfy { g in g.isEmpty || g.contains { fits(t, $0) } }
        }
        let name = { (t: Tile) in t.title.lowercased() }
        switch sort {
        case "Name Z–A": return keep.sorted { name($0) > name($1) }
        case "Recently played": return keep.sorted { ($0.played, name($1)) > ($1.played, name($0)) }
        case "Largest first": return keep.sorted { ($0.size ?? -1, name($1)) > ($1.size ?? -1, name($0)) }
        case "Installed first": return keep.sorted { ($0.installed ? 0 : 1, name($0)) < ($1.installed ? 0 : 1, name($1)) }
        case "Bottle": return keep.sorted { ($0.subtitle.lowercased(), name($0)) < ($1.subtitle.lowercased(), name($1)) }
        default: return keep.sorted { name($0) < name($1) }
        }
    }

    // ---------- running things ----------
    private func begin(_ message: String, cancellable: Bool = false) -> UUID {
        let id = UUID()
        tasks[id] = Running(message: message, cancellable: cancellable)
        return id
    }

    /// Runs a backend call with `message` in the sidebar; errors become an alert. Reloads the library afterwards.
    /// cancellable: installs and downloads, which get a cancel button.
    @discardableResult
    func task(_ message: String, _ call: String, _ args: [Any] = [], kw: [String: Any] = [:], reload: Bool = true,
              cancellable: Bool = false) async -> Any? {
        let id = begin(message, cancellable: cancellable)
        defer { tasks[id] = nil }
        do {
            let r = try await backend.call(call, args, kw: kw, job: cancellable ? id.uuidString : nil)
            if reload { await refresh() }
            return r
        } catch {
            if error.localizedDescription == "Cancelled" {
                notice = "Cancelled: \(message)"
                if reload { await refresh() }
            } else {
                await tell(error.localizedDescription)
            }
            return nil
        }
    }

    func launch(_ message: String, _ call: String, _ args: [Any] = [], kw: [String: Any] = [:], reload: Bool = true,
                cancellable: Bool = false) {
        Task { await task(message, call, args, kw: kw, reload: reload, cancellable: cancellable) }
    }

    func cancel(_ id: UUID) {
        guard let r = tasks[id] else { return }
        tasks[id] = Running(message: "Cancelling: \(r.message)", cancellable: false)
        Task { _ = try? await backend.call("cancel", [id.uuidString]) }
    }

    /// Like launch, then shows the message the call returns.
    func say(_ message: String, _ call: String, _ args: [Any] = []) {
        Task {
            if let text = await task(message, call, args) as? String { await tell(text) }
        }
    }

    // ---------- alerts ----------
    func ask(_ title: String, _ message: String = "", _ buttons: [String], text: String? = nil, cancel: Bool = true) async -> String? {
        await withCheckedContinuation { c in
            if questions.isEmpty { answerText = text ?? "" }
            questions.append(Question(title: title, message: message, buttons: buttons, cancel: cancel, text: text) {
                c.resume(returning: $0)
            })
        }
    }

    func tell(_ message: String) async {
        _ = await ask("Windows Portal", message, ["OK"], cancel: false)
    }

    func answer(_ button: String?) {
        guard !questions.isEmpty else { return }
        let q = questions.removeFirst()
        q.answer(button == nil ? nil : q.text == nil ? button : answerText)
        answerText = questions.first?.text ?? ""
    }

    func pickBottle(_ title: String) async -> String? {
        if let b = currentBottle { return b }
        if bottles.isEmpty {
            await tell("Create a bottle first (Manage Bottles → New Bottle).")
            return nil
        }
        return bottles.count == 1 ? bottles[0].name : await ask(title, "", bottles.map(\.name))
    }

    func choose(_ title: String, _ extensions: [String]) -> URL? {
        let panel = NSOpenPanel()
        panel.title = title
        panel.allowedContentTypes = extensions.compactMap { UTType(filenameExtension: $0) }
        return panel.runModal() == .OK ? panel.url : nil
    }

    // ---------- actions ----------
    func play(_ t: Tile) {
        Task {
            if let p = t.program { await play(p) } else if let s = t.store, let g = t.game { await play(s, g) }
        }
    }

    func play(_ p: Program) async {
        var r = await task("Starting \(p.title)…", "ui_play", [p.bottle, p.target, p.title], reload: false) as? [String: Any]
        if let why = r?["blocked"] as? String {
            guard await ask("Windows Portal", "Highball's database says \(p.title) won't run under Wine on a Mac: \(why).\n\n"
                            + "Launch anyway?", ["Launch Anyway"]) != nil else { return }
            r = await task("Starting \(p.title)…", "ui_play", [p.bottle, p.target, p.title, true], reload: false) as? [String: Any]
        }
        if r != nil, let i = programs.firstIndex(of: p) { programs[i].played = Date.now.timeIntervalSince1970 }
    }

    private func play(_ s: String, _ g: StoreGame) async {
        if g.mac == true && (g.macInstalled == true || g.installed == nil) {  // native beats Wine
            return getMac(s, g)
        }
        if g.installed == nil { return await install(s, g) }
        if await task("Starting \(g.title)…", "ui_store_play", [s, g.id], reload: false) != nil,
           let i = stores[s]?.games.firstIndex(of: g) {
            stores[s]?.games[i].played = Date.now.timeIntervalSince1970
        }
    }

    func playWindows(_ s: String, _ g: StoreGame) {
        launch("Starting \(g.title)…", "ui_store_play", [s, g.id], reload: false)
    }

    func getMac(_ s: String, _ g: StoreGame) {
        Task {
            if let text = await task("\(g.title): Mac version…", "store_mac", [s, g.id], reload: false) as? String {
                await tell(text)
            }
            await openStore(s, reload: true)
        }
    }

    func install(_ s: String, _ g: StoreGame) async {
        if s == "steam", let b = g.bottle {  // Steam downloads it in the bottle it's owned in
            await task("Opening Steam to install \(g.title)…", "store_install", [s, g.id, b], cancellable: true)
        } else if let b = await pickBottle("Install \(g.title) into which bottle?") {
            await task("Installing \(g.title) into \(b)… (large games take a while)", "store_install", [s, g.id, b], cancellable: true)
            await openStore(s, reload: true)
        }
    }

    func addProgram() async {
        guard let b = await pickBottle("Add a program to which bottle?"),
              let url = choose("Add a program to \(b)", ["exe", "lnk", "bat"]),
              let t = await ask("Add Program", "Name in library:", ["Add"], text: url.deletingPathExtension().lastPathComponent),
              !t.isEmpty else { return }
        await task("Adding \(t)…", "add_program", [b, url.path, t])
    }

    func gameSettings(_ p: Program, _ d: Detail) async {
        let labels = ["default"] + d.options
        guard let g = await ask("\(p.title): graphics", "Graphics for this game only (bottle: \(d.graphics)).", labels),
              await licensed(g, p.bottle),
              let m = await ask("\(p.title): mouse", "Force helps games whose camera spins or that lose the pointer.",
                                ["default", "enable", "force", "disable"]) else { return }
        let id = begin("Saving settings for \(p.title)…")
        defer { tasks[id] = nil }
        do {
            _ = try await backend.call("set_game", [p.bottle, p.target, "graphics", g])
            _ = try await backend.call("set_game", [p.bottle, p.target, "mouse", m])
        } catch {
            await tell(error.localizedDescription)
        }
    }

    /// D3DMetal on wine10 needs Apple's license accepted once.
    func licensed(_ layer: String, _ bottle: String) async -> Bool {
        let wine10 = bottles.first { $0.name == bottle }?.engine == "wine10"
        guard layer == "d3dmetal", wine10, let info, !info.d3dmetalAccepted else { return true }
        guard await ask("D3DMetal license", info.d3dmetalLicense, ["Accept"]) != nil else { return false }
        await task("Accepting…", "accept_d3dmetal", [false])
        return true
    }

    func connect(_ s: String) async {
        guard let how = await task("Opening \(storeName(s))…", "store_login_start", [s], reload: false) as? String,
              let code = await ask("Connect \(storeName(s))", how + "\n\nPaste it here:", ["Connect"], text: ""),
              !code.isEmpty else { return }
        await task("Connecting \(storeName(s))…", "store_login", [s, code], reload: false)
        stores[s] = nil
        await openStore(s, reload: true)
    }

    func disconnect(_ s: String) async {
        guard await ask("Disconnect \(storeName(s))?", "", ["Disconnect"]) != nil else { return }
        await task("Disconnecting…", "store_logout", [s], reload: false)
        stores[s] = nil
        await openStore(s, reload: true)
    }

    func coverArtKey() async {
        guard let k = await ask("Cover art", "Games also on Steam get Steam's covers. For the rest, paste a free SteamGridDB "
                                + "API key (steamgriddb.com → Preferences → API).\n\nNow: \(info?.artKey ?? "")",
                                ["Save"], text: ""), !k.isEmpty else { return }
        await task("Saving…", "ui_art_key", [k])
        artAsked.removeAll()
    }
}
