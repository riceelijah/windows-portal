// Windows Portal's window: sidebar of bottles and stores, a grid of programs and games, and Manage Bottles.
import AppKit
import ImageIO
import SwiftUI

@main struct WindowsPortalApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @State private var model = Model()

    var body: some Scene {
        Window("Windows Portal", id: "main") {
            ContentView().environment(model).frame(minWidth: 720, minHeight: 460)
        }
        .defaultSize(width: 1120, height: 720)
        Window("Manage Bottles", id: "bottles") {
            BottlesView().environment(model).frame(minWidth: 640, minHeight: 440).questions(model)
        }
        .defaultSize(width: 780, height: 540)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
}

extension View {
    /// Shows the model's questions one at a time.
    func questions(_ model: Model, main: Bool = false) -> some View { modifier(Questions(model: model, main: main)) }

    @ViewBuilder func prominent(_ on: Bool) -> some View {
        if on { buttonStyle(.borderedProminent) } else { self }
    }
}

/// The model's questions as a sheet, in the frontmost window only (each window carries this modifier); while the
/// app is in the background, in the main window.
/// A sheet, not an alert: alerts drop buttons (Cancel went missing) once there are a few.
struct Questions: ViewModifier {
    let model: Model
    let main: Bool
    @Environment(\.controlActiveState) private var active

    func body(content: Content) -> some View {
        let here = active == .key || (main && active == .inactive)
        content.sheet(isPresented: .constant(model.questions.first != nil && here)) {
            if let q = model.questions.first { QuestionView(q: q).environment(model) }
        }
    }
}

struct QuestionView: View {
    @Environment(Model.self) private var model
    let q: Question

    var body: some View {
        @Bindable var model = model
        let choice = q.text == nil && q.buttons.count > 1  // pick one of several: buttons stack, full width
        VStack(alignment: .leading, spacing: 12) {
            Text(q.title).font(.headline)
            if !q.message.isEmpty { Text(q.message).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
            if q.text != nil {
                TextField("", text: $model.answerText).textFieldStyle(.roundedBorder).onSubmit { model.answer(q.buttons.first) }
            }
            if choice {
                ForEach(q.buttons, id: \.self) { b in
                    Button { model.answer(b) } label: { Text(b).frame(maxWidth: .infinity) }.controlSize(.large)
                }
            }
            HStack {
                Spacer()
                if q.cancel { Button("Cancel", role: .cancel) { model.answer(nil) }.keyboardShortcut(.cancelAction) }
                if !choice {
                    ForEach(q.buttons, id: \.self) { b in Button(b) { model.answer(b) }.keyboardShortcut(.defaultAction) }
                }
            }
        }
        .padding(20).frame(width: 380)
    }
}

// ---------- main window ----------
struct ContentView: View {
    @Environment(Model.self) private var model
    @Environment(\.openWindow) private var openWindow
    @State private var query = ""
    @AppStorage("sort") private var sort = "Name A–Z"
    @State private var filters: Set<String> = []
    @State private var installing = false

    var body: some View {
        @Bindable var model = model
        let groups = model.filterGroups
        let ticked = groups.joined().filter(filters.contains).count
        NavigationSplitView {
            Sidebar().navigationSplitViewColumnWidth(min: 180, ideal: 210)
        } detail: {
            LibraryView(tiles: model.shown(query: query, sort: model.sorts.contains(sort) ? sort : "Name A–Z", filters: filters))
        }
        .searchable(text: $query, placement: .toolbar)
        .toolbar {
            ToolbarItemGroup {
                Picker("Sort", selection: $sort) { ForEach(model.sorts, id: \.self) { Text($0) } }
                    .pickerStyle(.menu).fixedSize()
                Menu {
                    ForEach(Array(groups.enumerated()), id: \.offset) { i, g in
                        if i > 0 { Divider() }
                        ForEach(g, id: \.self) { f in
                            Toggle(f, isOn: Binding(get: { filters.contains(f) },
                                                    set: { on in if on { filters.insert(f) } else { filters.remove(f) } }))
                        }
                    }
                } label: {
                    Label(ticked > 0 ? "Filters (\(ticked))" : "Filters", systemImage: "line.3.horizontal.decrease.circle")
                }
                Button { Task { await model.addProgram() } } label: { Label("Add Program…", systemImage: "plus") }
                Button { installing = true } label: { Label("Install Software…", systemImage: "square.and.arrow.down") }
                Button { openWindow(id: "bottles") } label: { Label("Manage Bottles", systemImage: "shippingbox") }
            }
        }
        .sheet(isPresented: $installing) { InstallSheet().environment(model) }
        .questions(model, main: true)
        .onChange(of: model.place) {
            model.selection = nil
            if case .store(let s)? = model.place { Task { await model.openStore(s) } }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // coming back to the window (e.g. after installing in Steam) shows what changed
            if Date.now.timeIntervalSince(model.lastRefresh) > 15 && model.tasks.isEmpty { Task { await model.refresh() } }
        }
    }
}

struct Sidebar: View {
    @Environment(Model.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: $model.place) {
            Label("All Programs", systemImage: "square.grid.2x2").tag(Place.all)
            if !model.bottles.isEmpty {
                Section("Bottles") {
                    ForEach(model.bottles, id: \.name) { b in
                        Label(b.name, systemImage: "shippingbox").tag(Place.bottle(b.name))
                    }
                }
            }
            Section("Stores") {
                ForEach(storeNames, id: \.key) { s in Label(s.name, systemImage: "bag").tag(Place.store(s.key)) }
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(model.tasks.sorted { $0.value.message < $1.value.message }, id: \.key) { id, t in
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text(t.message).lineLimit(2)
                        Spacer(minLength: 0)
                        if t.cancellable {
                            Button { model.cancel(id) } label: { Image(systemName: "xmark.circle.fill") }
                                .buttonStyle(.plain).foregroundStyle(.secondary).help("Cancel")
                        }
                    }
                }
                if let n = model.notice { Text(n).foregroundStyle(.secondary).lineLimit(3) }
            }
            .font(.caption).padding(12).frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct LibraryView: View {
    @Environment(Model.self) private var model
    let tiles: [Tile]

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: 14)], spacing: 14) {
                ForEach(tiles) { t in
                    TileView(tile: t, selected: model.selection == t.id).onAppear { model.wantArt(t); model.wantSize(t) }
                }
            }
            .padding(20)
        }
        .overlay { if tiles.isEmpty { empty } }
        .safeAreaInset(edge: .bottom, spacing: 0) { DetailBar(tile: tiles.first { $0.id == model.selection }) }
        .navigationTitle(model.title)
    }

    @ViewBuilder private var empty: some View {
        if case .store(let s)? = model.place {
            if s == "steam" {
                ContentUnavailableView("No Steam games yet", systemImage: "bag",
                                       description: Text("Install Steam in a bottle and sign in once: every game you own shows up here."))
            } else if model.stores[s]?.connected == false {
                ContentUnavailableView("Not connected", systemImage: "bag",
                                       description: Text("Connect your \(storeName(s)) account below."))
            } else if model.stores[s]?.games.isEmpty != false {
                ContentUnavailableView("Loading your library…", systemImage: "bag")
            } else {
                ContentUnavailableView.search
            }
        } else if model.tiles.isEmpty {
            ContentUnavailableView("No programs here yet", systemImage: "square.grid.2x2",
                                   description: Text("Use Install Software or Add Program in the toolbar."))
        } else {
            ContentUnavailableView("Nothing matches the search or filter", systemImage: "magnifyingglass")
        }
    }
}

struct TileView: View {
    @Environment(Model.self) private var model
    let tile: Tile
    let selected: Bool
    @State private var hover = false

    var body: some View {
        VStack(spacing: 6) {
            Thumb(path: tile.image).frame(width: 112, height: 112)
            Text(tile.title).font(.callout.weight(.semibold)).lineLimit(2).multilineTextAlignment(.center)
            Text(tile.subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            Text(tile.size.map(bytes) ?? " ").font(.caption2).foregroundStyle(.tertiary).monospacedDigit()
        }
        .padding(10)
        .frame(width: 160, height: 214, alignment: .top)
        .background(RoundedRectangle(cornerRadius: 10).fill(
            selected ? Color.accentColor.opacity(0.28) : Color.primary.opacity(hover ? 0.09 : 0.04)))
        .contentShape(RoundedRectangle(cornerRadius: 10))
        .onHover { hover = $0 }
        // Separate gestures, so a single click selects at once instead of waiting to see if it's a double-click.
        .gesture(TapGesture(count: 2).onEnded { model.selection = tile.id; model.play(tile) })
        .simultaneousGesture(TapGesture().onEnded { model.selection = tile.id })
        .contextMenu { Button("Play") { model.play(tile) } }
    }
}

/// An icon or cover, decoded off the main thread at tile size (never the full image), and cached.
struct Thumb: View {
    let path: String?
    @State private var image: CGImage?
    private static let cache = NSCache<NSString, CGImage>()

    var body: some View {
        Group {
            if let image {
                Image(decorative: image, scale: 2).resizable().aspectRatio(contentMode: .fit)
            } else {
                Image(nsImage: NSApp.applicationIconImage).resizable().aspectRatio(contentMode: .fit).opacity(0.35)
            }
        }
        .task(id: path) {
            guard let path else { return image = nil }
            if let hit = Self.cache.object(forKey: path as NSString) { return image = hit }
            image = await Task.detached(priority: .utility) { () -> CGImage? in
                guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil) else { return nil }
                let opts = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 224,
                            kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary
                return CGImageSourceCreateThumbnailAtIndex(src, 0, opts)
            }.value
            if let image { Self.cache.setObject(image, forKey: path as NSString) }
        }
    }
}

// ---------- the bar under the grid ----------
struct DetailBar: View {
    @Environment(Model.self) private var model
    let tile: Tile?

    var body: some View {
        HStack(spacing: 10) {
            if let t = tile, let p = t.program {
                ProgramDetail(p: p, size: t.size).id(t.id)
            } else if let t = tile, let s = t.store, let g = t.game {
                GameDetail(store: s, g: g, size: t.size).id(t.id)
            } else if case .store(let s)? = model.place {
                StoreBar(store: s)
            } else {
                Text("Select a program to see its options. Double-click to play.").foregroundStyle(.secondary)
                Spacer()
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 14)
        .frame(maxWidth: .infinity, minHeight: 92)
        .background(.bar)
    }
}

struct ProgramDetail: View {
    @Environment(Model.self) private var model
    let p: Program
    let size: Int64?
    @State private var d: Detail?
    @State private var verdict: Compat?

    var body: some View {
        Group { content }
            .task {
                d = try? await model.backend.get(Detail.self, "ui_detail", [p.bottle, p.target, p.title])
                if let a = p.appid { verdict = try? await model.backend.get(Compat.self, "ui_compat", [a, p.bottle]) }
            }
    }

    @ViewBuilder private var content: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(p.title).font(.title2.bold()).lineLimit(1)
            if let d {
                Text((["Bottle: \(p.bottle)", d.engine, "graphics: \(d.graphicsName)"] + [size.map(bytes)].compactMap { $0 })
                    .joined(separator: "  ·  ")).foregroundStyle(.secondary)
                if !d.own.isEmpty {
                    Text("This game: " + d.own.sorted { $0.key < $1.key }.map { "\($0.key) \($0.value)" }.joined(separator: ", "))
                        .foregroundStyle(.secondary)
                }
            }
            CompatLine(verdict: verdict, pending: p.appid != nil)
            if p.mac { Text("Has a Mac version on Steam").foregroundStyle(.green) }
        }
        .font(.callout)
        Spacer()
        if p.mac, let a = p.appid {
            Button("Get Mac Version") { model.say("\(p.title): Mac version…", "store_mac", ["steam", a]) }.prominent(true)
        }
        Button("▶  Play") { Task { await model.play(p) } }
            .prominent(!p.mac)
        if let d {
            Button("Game Settings…") { Task { await model.gameSettings(p, d) } }
            Button("Make Mac App") { model.say("Making a Mac app for \(p.title)…", "mac_app", [p.bottle, p.target, p.title]) }
            Button("Show Files") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: d.files)]) }
            if d.added {
                Button("Remove") { model.launch("Removing \(p.title)…", "remove_program", [p.bottle, p.title]) }
            } else {
                Button("Uninstall…") { model.launch("Opening the uninstaller…", "run", [p.bottle, "uninstaller"], kw: ["wait": false], reload: false) }
            }
        }
    }
}

/// Highball's compatibility verdict; click opens its page.
struct CompatLine: View {
    let verdict: Compat?
    let pending: Bool

    var body: some View {
        if let v = verdict {
            Button(v.verdict + "  ↗") { if let u = URL(string: v.url) { NSWorkspace.shared.open(u) } }
                .buttonStyle(.link).foregroundStyle(v.blocked ? Color.red : Color.secondary)
        } else if pending {
            Text("Checking compatibility…").foregroundStyle(.secondary)
        }
    }
}

struct GameDetail: View {
    @Environment(Model.self) private var model
    let store: String
    let g: StoreGame
    let size: Int64?
    @State private var download: Int64?  // not installed: what it downloads, asked of the store on selection
    @State private var verdict: Compat?
    @State private var looked = false

    var body: some View {
        let macFirst = g.mac == true && (g.macInstalled == true || g.installed == nil)
        VStack(alignment: .leading, spacing: 3) {
            Text(g.title).font(.title2.bold()).lineLimit(1)
            Text([storeName(store), g.installed ?? g.bottle, sizeText].compactMap { $0 }.joined(separator: "  ·  "))
                .foregroundStyle(.secondary)
            CompatLine(verdict: verdict, pending: !looked)
        }
        .font(.callout)
        .task {
            if g.installed == nil && store != "steam",
               let r = try? await model.backend.get(GameSize.self, "ui_game_size", [store, g.id]) { download = r.bytes }
        }
        .task {
            // umu matches other stores' games to Steam's, which Highball's database is keyed on
            if let a = try? await model.backend.call("umu_appid", [store, g.id]) as? String {
                verdict = try? await model.backend.get(Compat.self, "ui_compat", [a])
            }
            looked = true
        }
        Spacer()
        if g.mac == true {
            Button(g.macInstalled == true ? "▶  Play on Mac" : "Get Mac Version") { model.getMac(store, g) }.prominent(macFirst)
        }
        if g.installed != nil {
            Button(g.mac == true ? "▶  Play Windows Version" : "▶  Play") { model.playWindows(store, g) }.prominent(!macFirst)
        } else if g.windows ?? true {
            Button(store == "steam" ? (g.mac == true ? "Install Windows Version in Steam" : "Install in Steam")
                                    : (g.mac == true ? "Install Windows Version…" : "Install…")) {
                Task { await model.install(store, g) }
            }
            .prominent(!macFirst)
        }
    }
}

extension GameDetail {
    var sizeText: String? {
        if g.installed != nil { return size.map { "\(bytes($0)) on disk" } }
        if store == "steam" { return size.map { "about \(bytes($0)) to install" } }
        return download.map { "\(bytes($0)) download" }
    }
}

/// The bar for a store with nothing selected: its account.
struct StoreBar: View {
    @Environment(Model.self) private var model
    let store: String

    var body: some View {
        let connected = store == "steam" || model.stores[store]?.connected == true
        Text(store == "steam" ? "Your Steam library comes from the Steam you're signed in to in a bottle."
             : connected ? "Select a game. Double-click to install or play."
             : "Not connected. Sign in once; Windows Portal keeps the login on this Mac.")
            .foregroundStyle(.secondary)
        Spacer()
        if !connected {
            Button("Connect \(storeName(store))…") { Task { await model.connect(store) } }.prominent(true)
        } else {
            if store != "steam" { Button("Disconnect") { Task { await model.disconnect(store) } } }
            Button("Refresh") { Task { await model.openStore(store, reload: true) } }
            if store != "steam" { Button("Cover Art…") { Task { await model.coverArtKey() } } }
        }
    }
}

// ---------- Install Software ----------
struct InstallSheet: View {
    @Environment(Model.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var bottle = ""
    @State private var item: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Install Software").font(.title2.bold())
            if model.bottles.isEmpty {
                Text("Create a bottle first (Manage Bottles → New Bottle).").foregroundStyle(.secondary)
            } else {
                Picker("Into bottle", selection: $bottle) {
                    ForEach(model.bottles, id: \.name) { Text($0.name).tag($0.name) }
                }
                List(model.info?.catalog ?? [], id: \.self, selection: $item) { Text($0) }
                    .frame(minHeight: 260)
            }
            HStack {
                Button("Install from File…") {
                    let exts = ["exe", "msi"] + (model.info?.archives ?? []).map { String($0.split(separator: ".").last ?? "") }
                    guard let url = model.choose("Install into \(bottle)", exts) else { return }
                    dismiss()
                    model.launch("Installing \(url.lastPathComponent) into \(bottle)…", "install_file", [bottle, url.path], cancellable: true)
                }
                .disabled(bottle.isEmpty)
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Install") {
                    guard let item else { return }
                    dismiss()
                    model.launch("Installing \(item) into \(bottle)…", "install", [bottle, item], cancellable: true)
                }
                .keyboardShortcut(.defaultAction).disabled(item == nil || bottle.isEmpty)
            }
        }
        .padding(20).frame(width: 440)
        .onAppear { bottle = model.currentBottle ?? model.bottles.first?.name ?? "" }
    }
}

// ---------- Manage Bottles ----------
struct BottlesView: View {
    @Environment(Model.self) private var model
    @State private var selected: String?

    var body: some View {
        NavigationSplitView {
            List(model.bottles, id: \.name, selection: $selected) { b in
                VStack(alignment: .leading) {
                    Text(b.name)
                    Text(model.engineName(b.name)).font(.caption).foregroundStyle(.secondary)
                }
            }
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 6) {
                    Button("New Bottle…") { Task { await newBottle() } }
                    Button("Import…") {
                        if let url = model.choose("Import a bottle", ["gz"]) { model.launch("Importing…", "import_", [url.path], cancellable: true) }
                    }
                    if model.info?.engines["wine10"]?.installed == false {
                        Button("Get Wine 10 Engine") {
                            model.launch("Downloading the Wine 10 engine (~250 MB)…", "get_engine", ["wine10"], cancellable: true)
                        }
                    }
                    if model.info?.engines["arm64"]?.installed == false { Button("Get Native Engine…") { Task { await native() } } }
                }
                .buttonStyle(.borderless).padding(12).frame(maxWidth: .infinity, alignment: .leading)
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 220)
        } detail: {
            if let selected, model.bottles.contains(where: { $0.name == selected }) {
                BottleForm(name: selected).id(selected)
            } else {
                ContentUnavailableView("Select a bottle", systemImage: "shippingbox")
            }
        }
    }

    private func newBottle() async {
        let engines = (model.info?.engines ?? [:]).filter(\.value.installed).sorted { $0.key < $1.key }
        guard let n = await model.ask("New Bottle", "Bottle name:", ["Next"], text: ""), !n.isEmpty,
              let v = await model.ask("Windows version for \(n)", "", ["win11", "win10", "win7", "winxp64"]),
              let e = await model.ask("Engine for \(n)", "", engines.map(\.value.name)),
              let key = engines.first(where: { $0.value.name == e })?.key else { return }
        await model.task("Creating \(n)…", "new", [n, v, key], cancellable: true)
        selected = n
    }

    private func native() async {
        if let why = model.info?.arm64Missing { return await model.tell(why.prefix(1).uppercased() + why.dropFirst() + ".") }
        guard await model.ask("Native engine (preview)", "Wine built for Apple Silicon: Windows programs run through FEX "
                              + "instead of Rosetta. Graphics are vkd3d-proton and DXVK only (no D3DMetal or DXMT), so many "
                              + "games run slower than on wine10 for now. Bottles can't move to it: make a new one.\n\n"
                              + "Download it (~415 MB)?", ["Download"]) != nil else { return }
        await model.task("Downloading the native engine (~415 MB)…", "get_engine", ["arm64"], cancellable: true)
    }
}

struct BottleSettings: Decodable {
    var engine, graphics, display: String
    var options: [String]
    var sync: String?
}

struct WineSettings: Decodable { var keys, winver: String }

struct BottleForm: View {
    @Environment(Model.self) private var model
    let name: String
    @State private var s: BottleSettings?
    @State private var wine: WineSettings?  // asked of Wine, so it arrives after the rest
    @State private var size: Int64?

    var body: some View {
        Form {
            if let s {
                Section("Settings (restart the bottle's programs afterwards)") {
                    LabeledContent("Size on disk", value: size.map(bytes) ?? "Measuring…")
                    Picker("Engine", selection: bind(s.engine) { v in
                        await model.task("Switching \(name) to \(v)…", "set_engine", [name, v])
                    }) {
                        ForEach((model.info?.engines ?? [:]).filter { $0.value.installed || $0.key == s.engine }
                            .sorted { $0.key < $1.key }, id: \.key) { Text($0.value.name).tag($0.key) }
                    }
                    LabeledContent("Windows version") {
                        Menu(wine?.winver ?? "Checking…") {
                            ForEach(["win11", "win10", "win81", "win7", "winxp64"], id: \.self) { v in
                                Button(v) {
                                    wine = nil
                                    change { await model.task("Setting \(name) to \(v)…", "winver", [name, v], reload: false) }
                                }
                            }
                        }
                        .fixedSize().disabled(wine == nil)
                    }
                    Picker("Graphics", selection: bind(s.graphics) { v in
                        if await model.licensed(v, name) { await model.task("Setting \(name) to \(v)…", "set_graphics", [name, v]) }
                    }) {
                        ForEach(s.options, id: \.self) { Text(model.info?.renderers[$0] ?? $0).tag($0) }
                    }
                    if let sync = s.sync {
                        Picker("Sync", selection: bind(sync) { v in
                            await model.task("Setting \(name) to \(v)…", "sync_mode", [name, v], reload: false)
                        }) {
                            Text("msync: fastest for games").tag("msync")
                            Text("esync: in between").tag("esync")
                            Text("none: needed for Steam's own window").tag("none")
                        }
                    }
                    Picker("Display", selection: bind(s.display) { v in
                        await model.task("Setting \(name) to \(v)…", "display", [name, v], reload: false)
                    }) {
                        Text("Standard: Wine's default, fastest").tag("standard")
                        Text("Retina: full resolution, sharp").tag("retina")
                        Text("Compact: full resolution, smaller text").tag("compact")
                    }
                    Toggle("Command acts as Ctrl, Option as Alt", isOn: Binding(get: { wine?.keys == "on" }, set: { on in
                        wine?.keys = on ? "on" : "off"
                        change { await model.task("Updating \(name)…", "keys", [name, on], reload: false) }
                    }))
                    .disabled(wine == nil)
                }
                Section("Tools") {
                    tool("Run Program…") {
                        if let url = model.choose("Run a program in \(name)", ["exe", "msi", "bat", "lnk"]) {
                            await model.task("Starting \(url.lastPathComponent)…", "run", [name, url.path], kw: ["wait": false], reload: false)
                        }
                    }
                    tool("Open C: Drive") { await model.task("Opening…", "drive_c", [name], reload: false) }
                    tool("Wine Config") { await model.task("Opening Wine Config…", "run", [name, "winecfg"], kw: ["wait": false], reload: false) }
                    tool("Winetricks") { await model.task("Winetricks open…", "tricks", [name], reload: false) }
                    tool("Repair Steam") {
                        if let text = await model.task("Repairing Steam in \(name)… (up to 3 minutes)", "steam_repair", [name],
                                                       reload: false, cancellable: true) as? String {
                            await model.tell(text)
                        }
                    }
                    tool("Force Quit Everything") { await model.task("Stopping \(name)…", "kill", [name], reload: false) }
                    tool("Export…") {
                        let panel = NSSavePanel()
                        panel.nameFieldStringValue = "\(name).tar.gz"
                        if panel.runModal() == .OK, let url = panel.url {
                            let dest = url.path.hasSuffix(".tar.gz") ? String(url.path.dropLast(7)) : url.path
                            await model.task("Exporting \(name)…", "export", [name, dest], reload: false, cancellable: true)
                        }
                    }
                    tool("Delete Bottle…", role: .destructive) {
                        guard await model.ask("Delete \(name)?", "Permanently deletes the bottle, its Mac apps and everything "
                                              + "installed in it.", ["Delete"]) != nil else { return }
                        if model.currentBottle == name { model.place = .all }
                        await model.task("Deleting \(name)…", "delete", [name])
                    }
                }
            } else {
                ProgressView("Reading \(name)'s settings…")
            }
        }
        .formStyle(.grouped)
        .task { await load() }
        .task { size = (try? await model.backend.call("ui_bottle_size", [name]) as? NSNumber)?.int64Value }
    }

    private func load() async {
        do { s = try await model.backend.get(BottleSettings.self, "ui_bottle", [name]) }
        catch { return await model.tell(error.localizedDescription) }
        if wine == nil { wine = try? await model.backend.get(WineSettings.self, "ui_bottle_wine", [name]) }
    }

    /// Runs a change, then re-reads the settings (a refused change shows the old value again).
    private func change(_ work: @escaping () async -> Void) {
        Task { await work(); await load() }
    }

    private func bind(_ value: String, _ apply: @escaping (String) async -> Void) -> Binding<String> {
        Binding(get: { value }, set: { v in if v != value { change { await apply(v) } } })
    }

    private func tool(_ title: String, role: ButtonRole? = nil, _ work: @escaping () async -> Void) -> some View {
        Button(title, role: role) { Task { await work() } }
    }
}
