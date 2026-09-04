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
    title: "Mimaki PrintFlow PRO | Podbase Production Hub"
    color: "#f8fafc"

    property var appConfig: ({})
    property var activeInspectResult: null
    property string activePreviewUrl: ""
    property string activeLayer: "composite"
    property string activeFilePath: ""
    property string selectedProductId: ""
    property int selectedChoke: 1

    property string compositeStatus: "idle" // "idle", "running", "done", "error"
    property string compositeMessage: ""
    property string printStatus: "idle" // "idle", "running", "done", "error"
    property string printMessage: ""
    property string currentJobName: ""
    property bool rasterLinkVisibleOnScreen: false
    property bool autoPipelineEnabled: false

    onActiveLayerChanged: updatePreviewUrl()

    function updatePreviewUrl() {
        if (activeInspectResult && activeInspectResult.previews) {
            activePreviewUrl = activeInspectResult.previews[activeLayer] || activeInspectResult.previews["composite"] || ""
        } else {
            activePreviewUrl = ""
        }
    }

    // -------------------------------------------------------------
    // TOP HEADER BAR (PODBASE STYLE)
    // -------------------------------------------------------------
    header: ToolBar {
        background: Rectangle {
            color: "#ffffff"
            border.color: "#e2e8f0"
            border.width: 1
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 10

            // Podbase Logo
            Image {
                id: podbaseLogo
                source: "podbase_logo.png"
                height: 30
                fillMode: Image.PreserveAspectFit
                smooth: true
            }

            Rectangle {
                width: 1
                height: 24
                color: "#e2e8f0"
                Layout.leftMargin: 4
                Layout.rightMargin: 4
            }

            ColumnLayout {
                spacing: 1
                RowLayout {
                    spacing: 6
                    Text {
                        text: "PrintFlow"
                        color: "#1e1b4b"
                        font.bold: true
                        font.pixelSize: 15
                    }
                    Text {
                        text: "PRO"
                        color: "#f43f5e"
                        font.bold: true
                        font.pixelSize: 15
                    }
                    Rectangle {
                        color: "#f1f5f9"
                        border.color: "#e2e8f0"
                        radius: 4
                        height: 18
                        width: 96
                        Text {
                            anchors.centerIn: parent
                            text: "UJF-6042 MkII e"
                            color: "#475569"
                            font.bold: true
                            font.pixelSize: 9
                        }
                    }
                }
                Text {
                    text: "Mimaki Gamybos & Hot Folderių Valdiklis"
                    color: "#64748b"
                    font.pixelSize: 10
                }
            }

            Item { Layout.fillWidth: true }

            // Action Buttons (Podbase SaaS style)
            Button {
                id: btnToggleRL
                text: rasterLinkVisibleOnScreen ? "👁️ Slėpti RasterLink" : "👁️ Rodyti RasterLink"
                onClicked: printflowController.toggleRasterLink()
                background: Rectangle {
                    color: rasterLinkVisibleOnScreen ? "#eff6ff" : "#ffffff"
                    radius: 6
                    border.color: rasterLinkVisibleOnScreen ? "#3b82f6" : "#cbd5e1"
                }
                contentItem: Text {
                    text: rasterLinkVisibleOnScreen ? "👁️ Slėpti RasterLink" : "👁️ Rodyti RasterLink"
                    color: rasterLinkVisibleOnScreen ? "#1d4ed8" : "#334155"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: btnAutoPipeline
                text: autoPipelineEnabled ? "⚡ Konvejeris: ĮJUNGTAS" : "⚪ Konvejeris: IŠJUNGTAS"
                onClicked: printflowController.setAutoPipeline(!autoPipelineEnabled)
                background: Rectangle {
                    color: autoPipelineEnabled ? "#ecfdf5" : "#ffffff"
                    radius: 6
                    border.color: autoPipelineEnabled ? "#10b981" : "#cbd5e1"
                }
                contentItem: Text {
                    text: autoPipelineEnabled ? "⚡ Konvejeris: ĮJUNGTAS" : "⚪ Konvejeris: IŠJUNGTAS"
                    color: autoPipelineEnabled ? "#047857" : "#64748b"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: btnBatchPrepare
                text: "🚀 Paruošti Visus"
                onClicked: printflowController.batchPrepareAll()
                background: Rectangle {
                    color: "#f5f3ff"
                    radius: 6
                    border.color: "#c4b5fd"
                }
                contentItem: Text {
                    text: "🚀 Paruošti Visus"
                    color: "#6d28d9"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                text: "📂 Desktop\\mimaki"
                onClicked: printflowController.openStagingFolder()
                background: Rectangle {
                    color: "#fffbeb"
                    radius: 6
                    border.color: "#fde68a"
                }
                contentItem: Text {
                    text: "📂 Desktop\\mimaki"
                    color: "#b45309"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                text: "🔄 Atnaujinti"
                onClicked: printflowController.refreshInbox()
                background: Rectangle {
                    color: "#ffffff"
                    radius: 6
                    border.color: "#cbd5e1"
                }
                contentItem: Text {
                    text: "🔄 Atnaujinti"
                    color: "#334155"
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
                    color: "#ffffff"
                    radius: 6
                    border.color: "#cbd5e1"
                }
                contentItem: Text {
                    text: "🕒 Istorija"
                    color: "#334155"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                text: "⚙️ Nustatymai"
                onClicked: {
                    configDlg.populateFromConfig(appConfig)
                    configDlg.open()
                }
                background: Rectangle {
                    color: "#1e1b4b"
                    radius: 6
                }
                contentItem: Text {
                    text: "⚙️ Nustatymai"
                    color: "#ffffff"
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
                height: 215
                color: "#ffffff"
                radius: 12
                border.color: "#e2e8f0"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "📥 Gaunami Failai (Inbox Eilė)"
                            color: "#1e1b4b"
                            font.bold: true
                            font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "📂 Atverti failą..."
                            onClicked: openPdfDialog.open()
                            background: Rectangle {
                                color: "#f8fafc"
                                radius: 4
                                border.color: "#cbd5e1"
                            }
                            contentItem: Text {
                                text: "📂 Atverti failą..."
                                color: "#4338ca"
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

                    // Greita paieška pagal folderį, failą ar BID
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        TextField {
                            id: inboxFilterInput
                            Layout.fillWidth: true
                            placeholderText: "🔍 Filtruoti pagal folderį, BID ar pavadinimą..."
                            placeholderTextColor: "#94a3b8"
                            color: "#0f172a"
                            font.pixelSize: 11
                            leftPadding: 8
                            rightPadding: 8
                            topPadding: 4
                            bottomPadding: 4
                            background: Rectangle {
                                color: "#f8fafc"
                                radius: 6
                                border.color: "#cbd5e1"
                            }
                            onTextChanged: filterAndPopulateInbox()
                        }
                        Button {
                            visible: inboxFilterInput.text.length > 0
                            text: "✕"
                            onClicked: inboxFilterInput.text = ""
                            background: Rectangle { color: "#f1f5f9"; radius: 4; border.color: "#cbd5e1" }
                            contentItem: Text { text: "✕"; color: "#64748b"; font.pixelSize: 10 }
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
                                height: 52
                                color: activeFilePath === model.filepath ? "#eef2ff" : (inboxItemMouse.containsMouse ? "#f8fafc" : "#ffffff")
                                radius: 6
                                border.color: activeFilePath === model.filepath ? "#4f46e5" : (inboxItemMouse.containsMouse ? "#cbd5e1" : "#e2e8f0")
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
                                    anchors.margins: 6
                                    spacing: 8

                                    Text {
                                        text: activeFilePath === model.filepath ? "🔍" : (model.is_processed ? "🟢" : "📄")
                                        font.pixelSize: 14
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            Text {
                                                text: model.filename
                                                color: activeFilePath === model.filepath ? "#312e81" : "#0f172a"
                                                font.bold: true
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            Rectangle {
                                                visible: model.matched_product_name !== ""
                                                color: "#ecfdf5"
                                                border.color: "#a7f3d0"
                                                radius: 4
                                                height: 16
                                                width: Math.min(130, badgeText.contentWidth + 10)
                                                Text {
                                                    id: badgeText
                                                    anchors.centerIn: parent
                                                    text: model.matched_product_name || ""
                                                    color: "#047857"
                                                    font.pixelSize: 9
                                                    font.bold: true
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }

                                        RowLayout {
                                            spacing: 6
                                            Text {
                                                text: "📁 " + (model.rel_dir || "Šakninis")
                                                color: "#64748b"
                                                font.pixelSize: 9
                                            }
                                            Text {
                                                visible: !!model.matched_keyword
                                                text: "• 🏷️ " + model.matched_keyword
                                                color: "#0284c7"
                                                font.bold: true
                                                font.pixelSize: 9
                                            }
                                            Text {
                                                visible: !!model.bid
                                                text: "• BID: " + model.bid
                                                color: "#4f46e5"
                                                font.pixelSize: 9
                                                font.bold: true
                                            }
                                            Text {
                                                text: "• " + model.size_mb + " MB"
                                                color: "#94a3b8"
                                                font.pixelSize: 9
                                            }
                                        }
                                    }

                                    Rectangle {
                                        width: 58
                                        height: 22
                                        radius: 4
                                        color: activeFilePath === model.filepath ? "#f43f5e" : (model.is_processed ? "#10b981" : "#f1f5f9")
                                        border.color: activeFilePath === model.filepath ? "#f43f5e" : (model.is_processed ? "#10b981" : "#cbd5e1")
                                        Text {
                                            anchors.centerIn: parent
                                            text: activeFilePath === model.filepath ? "Aktyvus" : (model.is_processed ? "Paruoštas" : "Atidaryti")
                                            color: (activeFilePath === model.filepath || model.is_processed) ? "#ffffff" : "#334155"
                                            font.bold: true
                                            font.pixelSize: 9
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 2. READY TO PRINT QUEUE CARD (PARUOŠTI SPAUDAI)
            Rectangle {
                Layout.fillWidth: true
                height: readyJobsModel.count > 0 ? 175 : 68
                color: "#ffffff"
                radius: 12
                border.color: readyJobsModel.count > 0 ? "#10b981" : "#e2e8f0"
                border.width: readyJobsModel.count > 0 ? 2 : 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "🖨️ Paruošti Darbai Spaudai (RasterLink Paruošta)"
                            color: "#1e1b4b"
                            font.bold: true
                            font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            id: readyJobsCountText
                            text: readyJobsModel.count + " paruošti"
                            color: readyJobsModel.count > 0 ? "#059669" : "#94a3b8"
                            font.bold: true
                            font.pixelSize: 10
                        }
                    }

                    ListModel { id: readyJobsModel }

                    Text {
                        visible: readyJobsModel.count === 0
                        text: "Šiuo metu nėra paruoštų darbų. Pasirinkite failą arba spauskite 'Paruošti Visus'."
                        color: "#94a3b8"
                        font.pixelSize: 10
                        Layout.fillWidth: true
                    }

                    ScrollView {
                        visible: readyJobsModel.count > 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        ListView {
                            id: readyJobsListView
                            model: readyJobsModel
                            spacing: 4

                            delegate: Rectangle {
                                width: readyJobsListView.width
                                height: 44
                                color: "#f0fdf4"
                                radius: 6
                                border.color: "#86efac"
                                border.width: 1

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    spacing: 8

                                    Text {
                                        text: "🟢"
                                        font.pixelSize: 12
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Text {
                                            text: model.job_name
                                            color: "#065f46"
                                            font.bold: true
                                            font.pixelSize: 11
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            text: (model.product_name || "") + (model.bid ? (" • BID: " + model.bid) : "")
                                            color: "#047857"
                                            font.pixelSize: 9
                                        }
                                    }

                                    Button {
                                        text: "🖨️ RIP & PRINT"
                                        onClicked: printflowController.printReadyJob(model.job_name)
                                        background: Rectangle {
                                            color: "#f43f5e"
                                            radius: 6
                                        }
                                        contentItem: Text {
                                            text: "🖨️ RIP & PRINT"
                                            color: "#ffffff"
                                            font.bold: true
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
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
                color: "#ffffff"
                radius: 12
                border.color: "#e2e8f0"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    Text {
                        text: "1. Pasirinkite Gaminį"
                        color: "#1e1b4b"
                        font.bold: true
                        font.pixelSize: 12
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
                                color: selectedProductId === model.id ? "#f5f3ff" : "#f8fafc"
                                border.color: selectedProductId === model.id ? "#7c3aed" : "#e2e8f0"
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
                                        color: selectedProductId === model.id ? "#ede9fe" : "#ffffff"
                                        border.color: selectedProductId === model.id ? "#c4b5fd" : "#e2e8f0"
                                        Text { anchors.centerIn: parent; text: "📦"; font.pixelSize: 14 }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            text: model.name || ""
                                            color: "#0f172a"
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
                                        color: "#4338ca"
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
                                    background: Rectangle {
                                        color: selectedChoke === 1 ? "#7c3aed" : "#f1f5f9"
                                        border.color: selectedChoke === 1 ? "#7c3aed" : "#cbd5e1"
                                        radius: 4
                                    }
                                    contentItem: Text { text: "1 px"; color: selectedChoke === 1 ? "#ffffff" : "#334155"; font.bold: true; font.pixelSize: 10 }
                                }
                                Button {
                                    text: "2 px"
                                    onClicked: setChoke(2)
                                    background: Rectangle {
                                        color: selectedChoke === 2 ? "#7c3aed" : "#f1f5f9"
                                        border.color: selectedChoke === 2 ? "#7c3aed" : "#cbd5e1"
                                        radius: 4
                                    }
                                    contentItem: Text { text: "2 px"; color: selectedChoke === 2 ? "#ffffff" : "#334155"; font.bold: true; font.pixelSize: 10 }
                                }
                                Button {
                                    text: "0 px"
                                    onClicked: setChoke(0)
                                    background: Rectangle {
                                        color: selectedChoke === 0 ? "#7c3aed" : "#f1f5f9"
                                        border.color: selectedChoke === 0 ? "#7c3aed" : "#cbd5e1"
                                        radius: 4
                                    }
                                    contentItem: Text { text: "0 px"; color: selectedChoke === 0 ? "#ffffff" : "#334155"; font.bold: true; font.pixelSize: 10 }
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
                                placeholderTextColor: "#94a3b8"
                                color: "#0f172a"
                                font.pixelSize: 11
                                leftPadding: 8
                                rightPadding: 8
                                topPadding: 4
                                bottomPadding: 4
                                background: Rectangle { color: "#f8fafc"; radius: 6; border.color: "#cbd5e1" }
                            }
                        }
                    }

                    // GIANT DISPATCH BUTTON (PODBASE CORAL CTA)
                    Button {
                        id: btnDispatch
                        Layout.fillWidth: true
                        height: 52
                        enabled: activeFilePath !== "" && selectedProductId !== "" && compositeStatus !== "running" && printStatus !== "running"

                        background: Rectangle {
                            radius: 8
                            color: btnDispatch.enabled ? "#ff4d6d" : "#f1f5f9"
                            border.color: btnDispatch.enabled ? "#f43f5e" : "#e2e8f0"
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
                                color: btnDispatch.enabled ? "#ffffff" : "#94a3b8"
                                font.bold: true
                                font.pixelSize: 13
                            }
                            Item { Layout.fillWidth: true }
                        }

                        onClicked: {
                            currentJobName = jobNameInput.text.trim() || (activeInspectResult ? activeInspectResult.filename.replace(/\.[^/.]+$/, "") : "")
                            compositeStatus = "idle"
                            printStatus = "idle"
                            printflowController.dispatchJob(activeFilePath, selectedProductId, currentJobName, selectedChoke)
                        }
                    }

                    // RASTERLINK AUTOMATION STATUS & ACTION CARD
                    Rectangle {
                        id: rasterLinkActionCard
                        Layout.fillWidth: true
                        visible: compositeStatus !== "idle" || printStatus !== "idle"
                        radius: 8
                        color: {
                            if (printStatus === "done") return "#f0fdf4"
                            if (printStatus === "running") return "#eff6ff"
                            if (compositeStatus === "done") return "#f0fdf4"
                            if (compositeStatus === "running") return "#eff6ff"
                            if (compositeStatus === "error" || printStatus === "error") return "#fef2f2"
                            return "#f8fafc"
                        }
                        border.color: {
                            if (printStatus === "done") return "#86efac"
                            if (printStatus === "running") return "#93c5fd"
                            if (compositeStatus === "done") return "#86efac"
                            if (compositeStatus === "running") return "#93c5fd"
                            if (compositeStatus === "error" || printStatus === "error") return "#fca5a5"
                            return "#e2e8f0"
                        }
                        border.width: 1

                        implicitHeight: compColumn.implicitHeight + 24

                        ColumnLayout {
                            id: compColumn
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8

                            // Header status row
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    text: {
                                        if (printStatus === "done") return "🎉"
                                        if (printStatus === "running") return "🚀"
                                        if (compositeStatus === "done") return "✅"
                                        if (compositeStatus === "running") return "🔄"
                                        if (compositeStatus === "error" || printStatus === "error") return "⚠️"
                                        return "🖨️"
                                    }
                                    font.pixelSize: 14
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: {
                                        if (printStatus === "done") return "Spausdinimas paleistas į Mimaki UJF-6042 MkII e!"
                                        if (printStatus === "running") return "Vykdomas RIP ir Spausdinimas RasterLink 7..."
                                        if (compositeStatus === "done") return "Kompozicija paruošta: Primer ➔ White ➔ CMYK (Quality)"
                                        if (compositeStatus === "running") return "Fone jungiamos plokštės RasterLink 7 (Quality režimas)..."
                                        if (compositeStatus === "error") return "Kompozicijos klaida: " + compositeMessage
                                        if (printStatus === "error") return "Spausdinimo klaida: " + printMessage
                                        return "RasterLink 7 fono būsena"
                                    }
                                    color: {
                                        if (printStatus === "done") return "#065f46"
                                        if (printStatus === "running") return "#1e40af"
                                        if (compositeStatus === "done") return "#065f46"
                                        if (compositeStatus === "running") return "#1e40af"
                                        if (compositeStatus === "error" || printStatus === "error") return "#991b1b"
                                        return "#334155"
                                    }
                                    font.bold: true
                                    font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                }
                            }

                            // GIANT RIP & PRINT BUTTON (visible when composite is done)
                            Button {
                                id: btnPrintNow
                                Layout.fillWidth: true
                                height: 46
                                visible: compositeStatus === "done" && printStatus !== "done"
                                enabled: printStatus !== "running"

                                background: Rectangle {
                                    radius: 8
                                    color: "#f43f5e"
                                }

                                contentItem: RowLayout {
                                    spacing: 8
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        text: printStatus === "running" ? "⏳" : "🖨️"
                                        font.pixelSize: 16
                                    }
                                    Text {
                                        text: printStatus === "running" ? "SIUNČIAMA Į RIP & PRINT..." : "SPAUSDINTI DABAR (RIP & PRINT)"
                                        color: "#ffffff"
                                        font.bold: true
                                        font.pixelSize: 12
                                    }
                                    Item { Layout.fillWidth: true }
                                }

                                onClicked: {
                                    printflowController.executePrint(currentJobName)
                                }
                            }

                            // Toggle link to show/hide RasterLink
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: rasterLinkVisibleOnScreen ? "👁️ Slėpti RasterLink langą (grąžinti į foną)" : "👁️ Rodyti RasterLink langą (patikrinti būseną)"
                                    color: "#4338ca"
                                    font.pixelSize: 10
                                    font.underline: true
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: printflowController.toggleRasterLink()
                                    }
                                }
                                Item { Layout.fillWidth: true }
                            }
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
                color: "#ffffff"
                radius: 12
                border.color: "#e2e8f0"
                border.width: 1

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
                            color: "#1e1b4b"
                            font.bold: true
                            font.pixelSize: 13
                        }

                        // Active File Badge
                        Rectangle {
                            visible: activeInspectResult !== null
                            color: "#f0fdf4"
                            border.color: "#86efac"
                            border.width: 1
                            radius: 6
                            height: 24
                            width: activeFileContent.width + 16

                            RowLayout {
                                id: activeFileContent
                                anchors.centerIn: parent
                                spacing: 4
                                Text { text: "📄"; font.pixelSize: 11 }
                                Text {
                                    text: activeInspectResult ? activeInspectResult.filename : ""
                                    color: "#166534"
                                    font.bold: true
                                    font.pixelSize: 10
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }

                        Rectangle {
                            color: "#f8fafc"
                            border.color: "#e2e8f0"
                            radius: 6
                            height: 24
                            width: dimLabel.contentWidth + 16
                            Text {
                                id: dimLabel
                                anchors.centerIn: parent
                                text: "Matmenys: -- x -- mm (300 DPI)"
                                color: "#334155"
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
                            background: Rectangle {
                                color: activeLayer === "composite" ? "#1e1b4b" : "#f8fafc"
                                radius: 6
                                border.color: activeLayer === "composite" ? "#1e1b4b" : "#cbd5e1"
                            }
                            contentItem: Text {
                                text: "🌈 Visas vaizdas"
                                color: activeLayer === "composite" ? "#ffffff" : "#475569"
                                font.bold: true
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                            }
                            onClicked: activeLayer = "composite"
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "CMYK"
                            background: Rectangle {
                                color: activeLayer === "cmyk" ? "#1e1b4b" : "#f8fafc"
                                radius: 6
                                border.color: activeLayer === "cmyk" ? "#1e1b4b" : "#cbd5e1"
                            }
                            contentItem: Text {
                                text: "🎨 CMYK"
                                color: activeLayer === "cmyk" ? "#ffffff" : "#475569"
                                font.bold: true
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                            }
                            onClicked: activeLayer = "cmyk"
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "White Padas"
                            background: Rectangle {
                                color: activeLayer === "white" ? "#1e1b4b" : "#f8fafc"
                                radius: 6
                                border.color: activeLayer === "white" ? "#1e1b4b" : "#cbd5e1"
                            }
                            contentItem: Text {
                                text: "⚪ White Padas"
                                color: activeLayer === "white" ? "#ffffff" : "#0284c7"
                                font.bold: true
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                            }
                            onClicked: activeLayer = "white"
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "Primer Padas"
                            background: Rectangle {
                                color: activeLayer === "primer" ? "#1e1b4b" : "#f8fafc"
                                radius: 6
                                border.color: activeLayer === "primer" ? "#1e1b4b" : "#cbd5e1"
                            }
                            contentItem: Text {
                                text: "🟡 Primer Padas"
                                color: activeLayer === "primer" ? "#ffffff" : "#d97706"
                                font.bold: true
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                            }
                            onClicked: activeLayer = "primer"
                        }
                    }

                    // Image Canvas Area
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "#f8fafc"
                        radius: 8
                        border.color: "#e2e8f0"
                        border.width: 1
                        clip: true

                        // Checkerboard Transparency Background
                        Canvas {
                            id: checkerCanvas
                            anchors.fill: parent
                            visible: activeInspectResult !== null
                            onPaint: {
                                var ctx = getContext("2d");
                                var sz = 16;
                                ctx.fillStyle = "#ffffff";
                                ctx.fillRect(0, 0, width, height);
                                ctx.fillStyle = "#f1f5f9";
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
                            color: "#94a3b8"
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
                            height: 30
                            color: "#ffffff"
                            radius: 6
                            border.color: "#e2e8f0"
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
                                    color: activeLayer === "composite" ? "#16a34a" :
                                           activeLayer === "cmyk" ? "#2563eb" :
                                           activeLayer === "white" ? "#0284c7" : "#d97706"
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
                            color: "#d9ffffff"
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
                                    color: "#1e1b4b"
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
                height: 140
                color: "#ffffff"
                radius: 12
                border.color: "#e2e8f0"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "📋 Gamybos & Hot Folderių Žurnalas"
                            color: "#1e1b4b"
                            font.bold: true
                            font.pixelSize: 11
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "Mimaki UJF-6042 MkII e"
                            color: "#94a3b8"
                            font.pixelSize: 10
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "#0f172a"
                        radius: 8
                        border.color: "#1e293b"

                        ScrollView {
                            id: logScroll
                            anchors.fill: parent
                            anchors.margins: 8
                            clip: true

                            TextArea {
                                id: logArea
                                readOnly: true
                                color: "#38bdf8"
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

        property var rawInboxFiles: []

        function filterAndPopulateInbox() {
            var filterTxt = inboxFilterInput ? inboxFilterInput.text.trim().toLowerCase() : ""
            inboxModel.clear()
            var cnt = 0
            for (var i = 0; i < rawInboxFiles.length; i++) {
                var f = rawInboxFiles[i]
                if (filterTxt !== "") {
                    var matchRel = (f.rel_dir || "").toLowerCase().indexOf(filterTxt) !== -1
                    var matchFname = (f.filename || "").toLowerCase().indexOf(filterTxt) !== -1
                    var matchBid = (f.bid || "").toLowerCase().indexOf(filterTxt) !== -1
                    var matchProd = (f.matched_product_name || "").toLowerCase().indexOf(filterTxt) !== -1
                    var matchKw = (f.matched_keyword || "").toLowerCase().indexOf(filterTxt) !== -1
                    if (!matchRel && !matchFname && !matchBid && !matchProd && !matchKw) {
                        continue
                    }
                }
                inboxModel.append(f)
                cnt++
            }
            inboxCountText.text = cnt + (rawInboxFiles.length !== cnt ? (" iš " + rawInboxFiles.length) : " failų")
        }

        function onInboxUpdated(inboxJson) {
            try {
                var data = JSON.parse(inboxJson)
                rawInboxFiles = data.files || []
                filterAndPopulateInbox()
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

        function onCompositeStarted(jname) {
            compositeStatus = "running"
            compositeMessage = "Sujungiami sluoksniai RasterLink 7..."
        }

        function onCompositeFinished(resJson) {
            try {
                var res = JSON.parse(resJson)
                compositeStatus = "done"
                compositeMessage = res.message || "Kompozicija paruošta spaudai!"
            } catch (e) {
                compositeStatus = "done"
            }
        }

        function onCompositeFailed(err) {
            compositeStatus = "error"
            compositeMessage = err
        }

        function onPrintStarted(jname) {
            printStatus = "running"
            printMessage = "Siunčiama į RIP & Print..."
        }

        function onPrintFinished(resJson) {
            try {
                var res = JSON.parse(resJson)
                printStatus = "done"
                printMessage = res.message || "Spausdinimas paleistas!"
            } catch (e) {
                printStatus = "done"
            }
        }

        function onPrintFailed(err) {
            printStatus = "error"
            printMessage = err
        }

        function onLogMessage(msg) {
            logArea.append(msg)
        }

        function onHistoryUpdated(histJson) {
            historyDlg.populateHistory(histJson)
        }

        function onRasterLinkVisibilityChanged(isVis) {
            rasterLinkVisibleOnScreen = isVis
        }

        function onReadyJobsUpdated(jobsJson) {
            try {
                var jobs = JSON.parse(jobsJson)
                readyJobsModel.clear()
                for (var i = 0; i < jobs.length; i++) {
                    readyJobsModel.append(jobs[i])
                }
                readyJobsCountText.text = jobs.length + " paruošti"
            } catch (e) {}
        }

        function onAutoPipelineStatus(running) {
            autoPipelineEnabled = running
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
        rasterLinkVisibleOnScreen = printflowController.isRasterLinkVisible()
    }
}
