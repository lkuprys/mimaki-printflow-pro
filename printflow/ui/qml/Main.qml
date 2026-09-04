import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1340
    height: 840
    minimumWidth: 1024
    minimumHeight: 650
    title: "Mimaki PrintFlow PRO | UJF-6042 MkII e"
    color: "#090d16"

    property var appConfig: ({})
    property var activeInspectResult: null
    property string activePreviewUrl: ""
    property string activeLayer: "composite"
    property string activeFilePath: ""
    property string selectedProductId: ""
    property int selectedChoke: 1

    onActiveLayerChanged: updatePreviewUrl()

    function updatePreviewUrl() {
        if (activeInspectResult && activeInspectResult.previews) {
            activePreviewUrl = activeInspectResult.previews[activeLayer] || activeInspectResult.previews["composite"] || ""
        } else {
            activePreviewUrl = ""
        }
    }

    // -------------------------------------------------------------
    // TOP HEADER BAR
    // -------------------------------------------------------------
    header: ToolBar {
        background: Rectangle {
            color: "#0f172a"
            border.color: "#1e293b"
            border.width: 1
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 12

            // Icon & Title
            Rectangle {
                width: 38
                height: 38
                radius: 8
                color: "#15803d"
                Text {
                    anchors.centerIn: parent
                    text: "🖨️"
                    font.pixelSize: 18
                }
            }

            ColumnLayout {
                spacing: 1
                RowLayout {
                    spacing: 6
                    Text {
                        text: "Mimaki PrintFlow"
                        color: "#ffffff"
                        font.bold: true
                        font.pixelSize: 15
                    }
                    Text {
                        text: "PRO"
                        color: "#4ade80"
                        font.bold: true
                        font.pixelSize: 15
                    }
                    Rectangle {
                        color: "#052e16"
                        border.color: "#166534"
                        radius: 4
                        height: 18
                        width: 95
                        Text {
                            anchors.centerIn: parent
                            text: "UJF-6042 MkII e"
                            color: "#4ade80"
                            font.bold: true
                            font.pixelSize: 9
                        }
                    }
                }
                Text {
                    text: "Podbase Gamybos & Hot Folderių Valdiklis (Native Qt Desktop)"
                    color: "#64748b"
                    font.pixelSize: 10
                }
            }

            Item { Layout.fillWidth: true }

            // Action Buttons
            Button {
                text: "🔄 Atnaujinti Inbox"
                onClicked: printflowController.refreshInbox()
                background: Rectangle {
                    color: "#1e293b"
                    radius: 6
                    border.color: "#334155"
                }
                contentItem: Text {
                    text: "🔄 Atnaujinti Inbox"
                    color: "#e2e8f0"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: btnHistory
                text: "🕒 Istorija"
                onClicked: {
                    printflowController.loadHistory()
                    historyDlg.open()
                }
                background: Rectangle {
                    color: "#1e293b"
                    radius: 6
                    border.color: "#334155"
                }
                contentItem: Text {
                    text: "🕒 Istorija"
                    color: "#e2e8f0"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                text: "⚙️ Konfigūracija"
                onClicked: {
                    configDlg.populateFromConfig(appConfig)
                    configDlg.open()
                }
                background: Rectangle {
                    color: "#16a34a"
                    radius: 6
                }
                contentItem: Text {
                    text: "⚙️ Konfigūracija"
                    color: "#090d16"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    // -------------------------------------------------------------
    // MAIN WORKSPACE (2 COLUMNS)
    // -------------------------------------------------------------
    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        // =========================================================
        // LEFT COLUMN: INBOX, PRODUCTS & DISPATCH
        // =========================================================
        ColumnLayout {
            id: leftColumn
            Layout.fillWidth: false
            Layout.preferredWidth: 460
            Layout.maximumWidth: 520
            Layout.minimumWidth: 400
            Layout.fillHeight: true
            spacing: 14

            // 1. INBOX QUEUE CARD
            Rectangle {
                Layout.fillWidth: true
                height: 180
                color: "#131b2e"
                radius: 12
                border.color: "#1e293b"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "📥 Gaunami Failai (Inbox Eilė)"
                            color: "#ffffff"
                            font.bold: true
                            font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "📂 Atverti failą..."
                            onClicked: openPdfDialog.open()
                            background: Rectangle {
                                color: "#1e293b"
                                radius: 4
                                border.color: "#334155"
                            }
                            contentItem: Text {
                                text: "📂 Atverti failą..."
                                color: "#38bdf8"
                                font.bold: true
                                font.pixelSize: 10
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Text {
                            id: inboxCountText
                            text: "0 failų"
                            color: "#64748b"
                            font.pixelSize: 10
                        }
                    }

                    ListModel { id: inboxModel }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        ListView {
                            id: inboxListView
                            model: inboxModel
                            spacing: 4

                            delegate: Rectangle {
                                id: inboxItemRect
                                width: inboxListView.width
                                height: 40
                                color: activeFilePath === model.filepath ? "#064e3b" : (inboxItemMouse.containsMouse ? "#1e293b" : "#090d16")
                                radius: 6
                                border.color: activeFilePath === model.filepath ? "#34d399" : (inboxItemMouse.containsMouse ? "#334155" : "#1e293b")
                                border.width: activeFilePath === model.filepath ? 2 : 1

                                MouseArea {
                                    id: inboxItemMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: selectFile(model.filepath, model.matched_product_id)
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 8

                                    Text {
                                        text: activeFilePath === model.filepath ? "🔍" : "📄"
                                        font.pixelSize: 13
                                    }
                                    Text {
                                        text: model.filename
                                        color: activeFilePath === model.filepath ? "#34d399" : "#ffffff"
                                        font.bold: true
                                        font.pixelSize: 11
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                    }
                                    Rectangle {
                                        visible: model.matched_product_name !== ""
                                        color: "#052e16"
                                        border.color: "#166534"
                                        radius: 4
                                        height: 18
                                        width: Math.min(130, badgeText.contentWidth + 10)
                                        Text {
                                            id: badgeText
                                            anchors.centerIn: parent
                                            text: model.matched_product_name || ""
                                            color: "#4ade80"
                                            font.pixelSize: 9
                                            font.bold: true
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Text {
                                        text: model.size_mb + " MB"
                                        color: "#64748b"
                                        font.pixelSize: 10
                                    }
                                    Rectangle {
                                        width: 60
                                        height: 22
                                        radius: 4
                                        color: activeFilePath === model.filepath ? "#22c55e" : "#1e293b"
                                        Text {
                                            anchors.centerIn: parent
                                            text: activeFilePath === model.filepath ? "Aktyvus" : "Atidaryti"
                                            color: activeFilePath === model.filepath ? "#090d16" : "#cbd5e1"
                                            font.bold: true
                                            font.pixelSize: 10
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 2. PRODUCT PRESETS CARD
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#131b2e"
                radius: 12
                border.color: "#1e293b"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    Text {
                        text: "1. Pasirinkite Gaminį"
                        color: "#94a3b8"
                        font.bold: true
                        font.pixelSize: 11
                    }

                    ListModel { id: productsListModel }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        ListView {
                            id: prodListView
                            model: productsListModel
                            spacing: 6

                            delegate: Rectangle {
                                width: prodListView.width
                                height: 56
                                radius: 8
                                color: selectedProductId === model.id ? "#0e2a1e" : "#090d16"
                                border.color: selectedProductId === model.id ? "#22c55e" : "#1e293b"
                                border.width: selectedProductId === model.id ? 2 : 1

                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: {
                                        selectedProductId = model.id
                                        selectedChoke = model.choke_white_px !== undefined ? model.choke_white_px : 1
                                    }
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 10

                                    Rectangle {
                                        width: 32; height: 32; radius: 6
                                        color: "#131b2e"
                                        Text { anchors.centerIn: parent; text: "📦"; font.pixelSize: 14 }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            text: model.name || ""
                                            color: "#ffffff"
                                            font.bold: true
                                            font.pixelSize: 12
                                        }
                                        Text {
                                            text: "Choke: " + (model.choke_white_px !== undefined ? model.choke_white_px : 1) + " px | Raktas: " + (model.keyword || "-")
                                            color: "#64748b"
                                            font.pixelSize: 10
                                        }
                                    }

                                    Text {
                                        text: (model.layers ? model.layers.join(" • ") : "")
                                        color: "#38bdf8"
                                        font.bold: true
                                        font.pixelSize: 10
                                    }
                                }
                            }
                        }
                    }

                    // Choke & Job name row
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        ColumnLayout {
                            spacing: 4
                            Text { text: "Baltos Choke sutraukimas:"; color: "#64748b"; font.pixelSize: 10 }
                            RowLayout {
                                spacing: 4
                                Button {
                                    text: "1 px"
                                    onClicked: setChoke(1)
                                    background: Rectangle { color: selectedChoke === 1 ? "#22c55e" : "#1e293b"; radius: 4 }
                                    contentItem: Text { text: "1 px"; color: selectedChoke === 1 ? "#090d16" : "#ffffff"; font.bold: true; font.pixelSize: 10 }
                                }
                                Button {
                                    text: "2 px"
                                    onClicked: setChoke(2)
                                    background: Rectangle { color: selectedChoke === 2 ? "#22c55e" : "#1e293b"; radius: 4 }
                                    contentItem: Text { text: "2 px"; color: selectedChoke === 2 ? "#090d16" : "#ffffff"; font.bold: true; font.pixelSize: 10 }
                                }
                                Button {
                                    text: "0 px"
                                    onClicked: setChoke(0)
                                    background: Rectangle { color: selectedChoke === 0 ? "#22c55e" : "#1e293b"; radius: 4 }
                                    contentItem: Text { text: "0 px"; color: selectedChoke === 0 ? "#090d16" : "#ffffff"; font.bold: true; font.pixelSize: 10 }
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Text { text: "Partijos / Užsakymo pavadinimas:"; color: "#64748b"; font.pixelSize: 10 }
                            TextField {
                                id: jobNameInput
                                Layout.fillWidth: true
                                placeholderText: "Pagal failą..."
                                color: "#ffffff"
                                font.pixelSize: 11
                                background: Rectangle { color: "#090d16"; radius: 4; border.color: "#334155" }
                            }
                        }
                    }

                    // GIANT DISPATCH BUTTON
                    Button {
                        id: btnDispatch
                        Layout.fillWidth: true
                        height: 52
                        enabled: activeFilePath !== "" && selectedProductId !== ""

                        background: Rectangle {
                            radius: 10
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: btnDispatch.enabled ? "#22c55e" : "#334155" }
                                GradientStop { position: 1.0; color: btnDispatch.enabled ? "#14b8a6" : "#1e293b" }
                            }
                        }

                        contentItem: RowLayout {
                            spacing: 8
                            Item { Layout.fillWidth: true }
                            Text {
                                text: "⚡"
                                font.pixelSize: 16
                            }
                            Text {
                                id: dispatchBtnText
                                text: "SIŲSTI Į MIMAKI HOT FOLDERIUS"
                                color: btnDispatch.enabled ? "#090d16" : "#64748b"
                                font.bold: true
                                font.pixelSize: 13
                            }
                            Item { Layout.fillWidth: true }
                        }

                        onClicked: {
                            printflowController.dispatchJob(activeFilePath, selectedProductId, jobNameInput.text, selectedChoke)
                        }
                    }
                }
            }
        }

        // =========================================================
        // RIGHT COLUMN: 2D LAYER INSPECTOR & TERMINAL
        // =========================================================
        ColumnLayout {
            id: rightColumn
            Layout.fillWidth: true
            Layout.minimumWidth: 550
            Layout.fillHeight: true
            spacing: 14

            // 1. INSPECTOR CARD
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#131b2e"
                radius: 12
                border.color: "#1e293b"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    // Top row: Title & Active File Badge & Dimensions
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            text: "2. Sluoksnių Tikrintuvas (Pre-Press Inspector)"
                            color: "#ffffff"
                            font.bold: true
                            font.pixelSize: 12
                        }

                        // Active File Badge
                        Rectangle {
                            visible: activeInspectResult !== null
                            color: "#064e3b"
                            border.color: "#059669"
                            border.width: 1
                            radius: 4
                            height: 22
                            width: activeFileContent.width + 16

                            RowLayout {
                                id: activeFileContent
                                anchors.centerIn: parent
                                spacing: 4
                                Text { text: "📄"; font.pixelSize: 10 }
                                Text {
                                    text: activeInspectResult ? activeInspectResult.filename : ""
                                    color: "#34d399"
                                    font.bold: true
                                    font.pixelSize: 10
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }

                        Rectangle {
                            color: "#090d16"
                            radius: 4
                            height: 22
                            width: dimLabel.contentWidth + 16
                            Text {
                                id: dimLabel
                                anchors.centerIn: parent
                                text: "Matmenys: -- x -- mm (300 DPI)"
                                color: "#38bdf8"
                                font.bold: true
                                font.pixelSize: 10
                            }
                        }
                    }

                    // Layer Selection Tabs
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Button {
                            Layout.fillWidth: true
                            text: "Visas vaizdas"
                            background: Rectangle { color: activeLayer === "composite" ? "#22c55e" : "#090d16"; radius: 6; border.color: activeLayer === "composite" ? "#16a34a" : "#1e293b" }
                            contentItem: Text { text: "🌈 Visas vaizdas"; color: activeLayer === "composite" ? "#090d16" : "#cbd5e1"; font.bold: true; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter }
                            onClicked: activeLayer = "composite"
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "CMYK"
                            background: Rectangle { color: activeLayer === "cmyk" ? "#22c55e" : "#090d16"; radius: 6; border.color: activeLayer === "cmyk" ? "#16a34a" : "#1e293b" }
                            contentItem: Text { text: "🎨 CMYK"; color: activeLayer === "cmyk" ? "#090d16" : "#cbd5e1"; font.bold: true; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter }
                            onClicked: activeLayer = "cmyk"
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "White Padas"
                            background: Rectangle { color: activeLayer === "white" ? "#22c55e" : "#090d16"; radius: 6; border.color: activeLayer === "white" ? "#16a34a" : "#1e293b" }
                            contentItem: Text { text: "⚪ White Padas"; color: activeLayer === "white" ? "#090d16" : "#38bdf8"; font.bold: true; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter }
                            onClicked: activeLayer = "white"
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "Primer Padas"
                            background: Rectangle { color: activeLayer === "primer" ? "#22c55e" : "#090d16"; radius: 6; border.color: activeLayer === "primer" ? "#16a34a" : "#1e293b" }
                            contentItem: Text { text: "🟡 Primer Padas"; color: activeLayer === "primer" ? "#090d16" : "#fbbf24"; font.bold: true; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter }
                            onClicked: activeLayer = "primer"
                        }
                    }

                    // Image Canvas Area
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "#0b0f19"
                        radius: 8
                        clip: true

                        // Checkerboard Transparency Background
                        Canvas {
                            id: checkerCanvas
                            anchors.fill: parent
                            visible: activeInspectResult !== null
                            onPaint: {
                                var ctx = getContext("2d");
                                var sz = 16;
                                ctx.fillStyle = "#0b0f19";
                                ctx.fillRect(0, 0, width, height);
                                ctx.fillStyle = "#131b2e";
                                for (var x = 0; x < width; x += sz) {
                                    for (var y = 0; y < height; y += sz) {
                                        if (((Math.floor(x / sz) + Math.floor(y / sz)) % 2) === 0) {
                                            ctx.fillRect(x, y, sz, sz);
                                        }
                                    }
                                }
                            }
                            onWidthChanged: requestPaint()
                            onHeightChanged: requestPaint()
                        }

                        DropArea {
                            anchors.fill: parent
                            onDropped: (drop) => {
                                if (drop.hasUrls && drop.urls.length > 0) {
                                    var u = drop.urls[0].toString()
                                    var p = u.replace(/^(file:\/{3}|file:\/\/)/, "")
                                    p = decodeURIComponent(p)
                                    selectFile(p, "")
                                }
                            }
                        }

                        // Placeholder
                        Text {
                            anchors.centerIn: parent
                            visible: activeInspectResult === null && !loadingIndicator.visible
                            text: "Pasirinkite failą iš Inbox eilės arba įtempkite failą čia"
                            color: "#475569"
                            font.pixelSize: 12
                        }

                        // Preview Image
                        Image {
                            id: previewImage
                            anchors.fill: parent
                            anchors.margins: 12
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            asynchronous: true
                            cache: false
                            visible: activeInspectResult !== null && activePreviewUrl !== ""
                            source: activePreviewUrl
                        }

                        // Layer Info Legend Bar (Bottom)
                        Rectangle {
                            anchors.bottom: parent.bottom
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.margins: 8
                            height: 28
                            color: "#ee090d16"
                            radius: 6
                            border.color: "#1e293b"
                            visible: activeInspectResult !== null

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8

                                Text {
                                    text: activeLayer === "composite" ? "🌈 Visas vaizdas: Pilnas spaudos dizainas (su permatomu fonu)" :
                                          activeLayer === "cmyk" ? "🎨 CMYK Plokštė: Tik spalvinis sluoksnis spausdinimui" :
                                          activeLayer === "white" ? "⚪ White Plokštė: Baltas padas (Cyan spalva žymi " + selectedChoke + "px Choke eroziją)" :
                                          "🟡 Primer Plokštė: Sukibimo grunto padas (Gintarinė spalva)"
                                    color: activeLayer === "composite" ? "#4ade80" :
                                           activeLayer === "cmyk" ? "#38bdf8" :
                                           activeLayer === "white" ? "#7dd3fc" : "#fbbf24"
                                    font.pixelSize: 10
                                    font.bold: true
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }

                                Text {
                                    text: activeInspectResult ? (activeInspectResult.width_px + " × " + activeInspectResult.height_px + " px @ 300 DPI") : ""
                                    color: "#64748b"
                                    font.pixelSize: 9
                                }
                            }
                        }

                        // Loading Indicator
                        Rectangle {
                            id: loadingIndicator
                            anchors.fill: parent
                            color: "#cc090d16"
                            visible: false

                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 8
                                BusyIndicator {
                                    running: loadingIndicator.visible
                                    Layout.alignment: Qt.AlignHCenter
                                }
                                Text {
                                    id: loadingText
                                    text: "Apdorojamas failas..."
                                    color: "#4ade80"
                                    font.bold: true
                                }
                            }
                        }
                    }
                }
            }

            // 2. DISPATCH TERMINAL LOG
            Rectangle {
                Layout.fillWidth: true
                height: 130
                color: "#090d16"
                radius: 10
                border.color: "#1e293b"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 4

                    Text {
                        text: "📋 Gamybos & Hot Folderių Žurnalas"
                        color: "#64748b"
                        font.bold: true
                        font.pixelSize: 10
                    }

                    ScrollView {
                        id: logScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        TextArea {
                            id: logArea
                            readOnly: true
                            color: "#a7f3d0"
                            font.family: "Consolas"
                            font.pixelSize: 10
                            wrapMode: TextArea.Wrap
                            background: Rectangle { color: "transparent" }
                        }
                    }
                }
            }
        }
    }

    // -------------------------------------------------------------
    // CONTROLLER SIGNALS CONNECTION
    // -------------------------------------------------------------
    Connections {
        target: printflowController

        function onConfigLoaded(cfgJson) {
            try {
                appConfig = JSON.parse(cfgJson)
                productsListModel.clear()
                for (var i = 0; i < appConfig.products.length; i++) {
                    productsListModel.append(appConfig.products[i])
                }
                if (appConfig.products.length > 0 && selectedProductId === "") {
                    selectedProductId = appConfig.products[0].id
                    selectedChoke = appConfig.products[0].choke_white_px || 1
                }
            } catch (e) {}
        }

        function onInboxUpdated(inboxJson) {
            try {
                var data = JSON.parse(inboxJson)
                inboxModel.clear()
                for (var i = 0; i < data.files.length; i++) {
                    inboxModel.append(data.files[i])
                }
                inboxCountText.text = data.count + " failų"
            } catch (e) {}
        }

        function onInspectStarted() {
            loadingIndicator.visible = true
            loadingText.text = "Apdorojama 35.6 MP kaukė..."
        }

        function onInspectFinished(resJson) {
            loadingIndicator.visible = false
            try {
                var res = JSON.parse(resJson)
                activeInspectResult = res
                activeFilePath = res.filepath
                updatePreviewUrl()
                dimLabel.text = "Matmenys: " + res.width_mm + " x " + res.height_mm + " mm (" + res.width_px + " x " + res.height_px + " px)"
                jobNameInput.text = res.filename.replace(/\.[^/.]+$/, "")
            } catch (e) {}
        }

        function onInspectFailed(err) {
            loadingIndicator.visible = false
        }

        function onDispatchStarted() {
            btnDispatch.enabled = false
            dispatchBtnText.text = "Generuojamos plokštės & siunčiama..."
        }

        function onDispatchFinished(resJson) {
            btnDispatch.enabled = true
            dispatchBtnText.text = "SĖKMINGAI NUSIŲSTA Į HOT FOLDERIUS!"
            refreshTimer.start()
        }

        function onDispatchFailed(err) {
            btnDispatch.enabled = true
            dispatchBtnText.text = "KLAIDA: " + err
            refreshTimer.start()
        }

        function onLogMessage(msg) {
            logArea.append(msg)
        }

        function onHistoryUpdated(histJson) {
            historyDlg.populateHistory(histJson)
        }
    }

    Timer {
        id: refreshTimer
        interval: 3000
        repeat: false
        onTriggered: {
            dispatchBtnText.text = "SIŲSTI Į MIMAKI HOT FOLDERIUS"
        }
    }

    function setChoke(px) {
        selectedChoke = px
        if (activeFilePath !== "") {
            printflowController.inspectFile(activeFilePath, selectedChoke)
        }
    }

    function selectFile(fpath, matchedProdId) {
        activeFilePath = fpath
        if (matchedProdId && matchedProdId !== "") {
            selectedProductId = matchedProdId
        }
        printflowController.inspectFile(fpath, selectedChoke)
    }

    // Modal Dialogs
    ConfigDialog { id: configDlg }
    HistoryDialog { id: historyDlg }

    FileDialog {
        id: openPdfDialog
        title: "Pasirinkite spaudos PDF / TIFF failą"
        nameFilters: ["Spaudos failai (*.pdf *.tif *.tiff)", "PDF failai (*.pdf)", "TIFF failai (*.tif *.tiff)", "Visi failai (*)"]
        onAccepted: {
            var p = selectedFile.toString().replace(/^(file:\/{3}|file:\/\/)/, "")
            p = decodeURIComponent(p)
            selectFile(p, "")
        }
    }

    Component.onCompleted: {
        printflowController.loadConfig()
        printflowController.refreshInbox()
    }
}
