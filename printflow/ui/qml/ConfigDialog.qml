import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: configDialog
    title: "Sistemos Konfigūracija & Gaminiai"
    modal: true
    focus: true
    width: Math.min(850, parent.width - 40)
    height: Math.min(650, parent.height - 40)
    anchors.centerIn: parent

    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#e2e8f0"
        border.width: 1
    }

    header: Rectangle {
        color: "#f8fafc"
        height: 52
        radius: 12
        border.color: "#e2e8f0"
        border.width: 1
        
        RowLayout {
            anchors.fill: parent
            anchors.margins: 14

            Text {
                text: "⚙️ Sistemos Nustatymai & Gaminiai"
                color: "#1e1b4b"
                font.bold: true
                font.pixelSize: 15
                Layout.fillWidth: true
            }

            Button {
                text: "✕"
                onClicked: configDialog.close()
                background: Rectangle {
                    color: "transparent"
                }
                contentItem: Text {
                    text: "✕"
                    color: "#64748b"
                    font.pixelSize: 16
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    property var currentProducts: []

    function populateFromConfig(cfg) {
        inboxInput.text = cfg.inbox_folder || ""
        folderFilterInput.text = cfg.folder_filter_keywords ? (Array.isArray(cfg.folder_filter_keywords) ? cfg.folder_filter_keywords.join(", ") : cfg.folder_filter_keywords) : ""
        stagingInput.text = cfg.staging_folder || ""
        autoPipelineCheckBox.checked = !!cfg.auto_pipeline
        currentProducts = cfg.products ? JSON.parse(JSON.stringify(cfg.products)) : []
        productsModel.clear()
        for (var i = 0; i < currentProducts.length; i++) {
            var p = currentProducts[i]
            var kws = p.keywords ? (Array.isArray(p.keywords) ? p.keywords.join(", ") : p.keywords) : (p.keyword || "")
            p.keywords_str = kws
            p.keyword = kws
            productsModel.append(p)
        }
    }

    contentItem: ColumnLayout {
        spacing: 12

        // Inbox folder & Folder Filter Keywords
        Rectangle {
            Layout.fillWidth: true
            height: 120
            color: "#f8fafc"
            radius: 8
            border.color: "#e2e8f0"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4

                Text {
                    text: "📁 Bendras gamybos aplankas (Inbox / Tinklo kelias su subfolderiais):"
                    color: "#1e1b4b"
                    font.bold: true
                    font.pixelSize: 11
                }

                TextField {
                    id: inboxInput
                    Layout.fillWidth: true
                    color: "#0f172a"
                    font.pixelSize: 12
                    placeholderText: "Pvz.: Z:\\GAMYBA\\UZSAKYMAI arba E:\\Projektai\\TEST\\INBOX_PRINT_FILES"
                    background: Rectangle {
                        color: "#ffffff"
                        radius: 6
                        border.color: "#cbd5e1"
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "🔍 Katalogų paieškos filtrai (nebūtina, atskirti kableliais):"
                        color: "#475569"
                        font.bold: true
                        font.pixelSize: 10
                    }
                    Text {
                        text: "(ieškos tik aplankuose su šiais žodžiais, pvz.: GEN1, 2026)"
                        color: "#64748b"
                        font.pixelSize: 9
                    }
                }

                TextField {
                    id: folderFilterInput
                    Layout.fillWidth: true
                    color: "#0f172a"
                    font.pixelSize: 11
                    placeholderText: "Pvz.: GEN1, 2026 (jei tuščia — ieško visuose pakatalogiuose)"
                    background: Rectangle {
                        color: "#ffffff"
                        radius: 6
                        border.color: "#cbd5e1"
                    }
                }
            }
        }

        // Staging folder & Auto Pipeline settings
        Rectangle {
            Layout.fillWidth: true
            height: 98
            color: "#f8fafc"
            radius: 8
            border.color: "#e2e8f0"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "💻 Lokalus paruoštų plokščių aplankas (Staging):"
                        color: "#1e1b4b"
                        font.bold: true
                        font.pixelSize: 11
                        Layout.fillWidth: true
                    }
                    Button {
                        text: "Nustatyti į Desktop\\mimaki"
                        onClicked: stagingInput.text = "C:\\Users\\" + (Qt.platform.os === "windows" ? Qt.application.arguments[0].split("\\")[2] : "user") + "\\Desktop\\mimaki"
                        background: Rectangle { color: "#ffffff"; radius: 4; border.color: "#cbd5e1" }
                        contentItem: Text { text: "Nustatyti į Desktop\\mimaki"; color: "#2563eb"; font.pixelSize: 10; font.bold: true }
                    }
                }

                TextField {
                    id: stagingInput
                    Layout.fillWidth: true
                    color: "#0f172a"
                    font.pixelSize: 12
                    placeholderText: "Pvz.: C:\\Users\\Vartotojas\\Desktop\\mimaki"
                    background: Rectangle {
                        color: "#ffffff"
                        radius: 6
                        border.color: "#cbd5e1"
                    }
                }

                RowLayout {
                    spacing: 8
                    CheckBox {
                        id: autoPipelineCheckBox
                        text: "⚡ Įjungti nuolatinį foninį gamybos konvejerį (Auto-Pipeline)"
                        contentItem: Text {
                            text: autoPipelineCheckBox.text
                            color: "#1e1b4b"
                            font.pixelSize: 11
                            font.bold: true
                            leftPadding: autoPipelineCheckBox.indicator.width + 6
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }

        // Products header
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Spausdinami Gaminiai:"
                color: "#1e1b4b"
                font.bold: true
                font.pixelSize: 13
                Layout.fillWidth: true
            }

            Button {
                text: "+ Pridėti Naują Gaminį"
                onClicked: {
                    var newP = {
                        "id": "prod_" + Date.now(),
                        "name": "Naujas Gaminys",
                        "keyword": "raktas1, raktas2",
                        "keywords": ["raktas1", "raktas2"],
                        "keywords_str": "raktas1, raktas2",
                        "layers": ["Primer", "White", "CMYK"],
                        "choke_white_px": 1,
                        "choke_primer_px": 0,
                        "hotfolders": { "CMYK": "", "White": "", "Primer": "" }
                    }
                    productsModel.append(newP)
                }
                background: Rectangle {
                    color: "#1e1b4b"
                    radius: 6
                }
                contentItem: Text {
                    text: "+ Pridėti Naują Gaminį"
                    color: "#ffffff"
                    font.bold: true
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        // Products List
        ListModel {
            id: productsModel
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ListView {
                id: productsView
                model: productsModel
                spacing: 8

                delegate: Rectangle {
                    width: productsView.width
                    height: 195
                    color: "#f8fafc"
                    radius: 8
                    border.color: "#e2e8f0"
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6

                        // Row 1: Name & Delete
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "Pavadinimas:"; color: "#475569"; font.pixelSize: 11; font.bold: true }
                            TextField {
                                id: nameField
                                Layout.fillWidth: true
                                text: model.name || ""
                                color: "#0f172a"
                                font.bold: true
                                font.pixelSize: 12
                                background: Rectangle { color: "#ffffff"; radius: 4; border.color: "#cbd5e1" }
                                onTextChanged: productsModel.setProperty(index, "name", text)
                            }
                            Button {
                                text: "Ištrinti"
                                onClicked: productsModel.remove(index)
                                background: Rectangle { color: "#fef2f2"; radius: 4; border.color: "#fecaca" }
                                contentItem: Text { text: "Ištrinti"; color: "#dc2626"; font.pixelSize: 11; font.bold: true }
                            }
                        }

                        // Row 2: Multiple Keywords & Choke
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: "Raktažodžiai (folderių / failų):"; color: "#1e1b4b"; font.pixelSize: 11; font.bold: true }
                            TextField {
                                id: kwField
                                Layout.fillWidth: true
                                text: model.keywords_str !== undefined ? model.keywords_str : (model.keyword || "")
                                placeholderText: "Pvz.: magsafe-ring-holders, ring-holder, RH (atskirti kableliais)"
                                color: "#0f172a"
                                font.pixelSize: 11
                                background: Rectangle { color: "#ffffff"; radius: 4; border.color: "#cbd5e1" }
                                onTextChanged: {
                                    productsModel.setProperty(index, "keyword", text)
                                    productsModel.setProperty(index, "keywords_str", text)
                                }
                            }

                            Text { text: "Choke:"; color: "#475569"; font.pixelSize: 11; font.bold: true }
                            SpinBox {
                                id: chokeSpin
                                from: 0; to: 20
                                value: model.choke_white_px !== undefined ? model.choke_white_px : 1
                                onValueChanged: productsModel.setProperty(index, "choke_white_px", value)
                            }
                        }

                        // Row 3: Hotfolders
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3

                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "CMYK HotFolder:"; color: "#64748b"; font.pixelSize: 10; Layout.preferredWidth: 100 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: model.hotfolders ? (model.hotfolders.CMYK || "") : ""
                                    color: "#334155"
                                    font.pixelSize: 10
                                    background: Rectangle { color: "#ffffff"; radius: 4; border.color: "#e2e8f0" }
                                    onTextChanged: {
                                        var hf = model.hotfolders || {}
                                        hf.CMYK = text
                                        productsModel.setProperty(index, "hotfolders", hf)
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "White HotFolder:"; color: "#64748b"; font.pixelSize: 10; Layout.preferredWidth: 100 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: model.hotfolders ? (model.hotfolders.White || "") : ""
                                    color: "#334155"
                                    font.pixelSize: 10
                                    background: Rectangle { color: "#ffffff"; radius: 4; border.color: "#e2e8f0" }
                                    onTextChanged: {
                                        var hf = model.hotfolders || {}
                                        hf.White = text
                                        productsModel.setProperty(index, "hotfolders", hf)
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "Primer HotFolder:"; color: "#64748b"; font.pixelSize: 10; Layout.preferredWidth: 100 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: model.hotfolders ? (model.hotfolders.Primer || "") : ""
                                    color: "#334155"
                                    font.pixelSize: 10
                                    background: Rectangle { color: "#ffffff"; radius: 4; border.color: "#e2e8f0" }
                                    onTextChanged: {
                                        var hf = model.hotfolders || {}
                                        hf.Primer = text
                                        productsModel.setProperty(index, "hotfolders", hf)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    footer: Rectangle {
        color: "#f8fafc"
        height: 55
        radius: 12
        border.color: "#e2e8f0"
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.margins: 12

            Text {
                id: statusMsg
                text: ""
                color: "#16a34a"
                font.bold: true
                font.pixelSize: 11
                Layout.fillWidth: true
            }

            Button {
                text: "Atšaukti"
                onClicked: configDialog.close()
                background: Rectangle { color: "#ffffff"; radius: 6; border.color: "#cbd5e1" }
                contentItem: Text { text: "Atšaukti"; color: "#475569"; font.bold: true; font.pixelSize: 12 }
            }

            Button {
                text: "💾 Išsaugoti Pakeitimus"
                onClicked: {
                    var outProds = []
                    for (var i = 0; i < productsModel.count; i++) {
                        var item = productsModel.get(i)
                        var rawKws = item.keywords_str !== undefined ? item.keywords_str : (item.keyword || "")
                        var kwsList = []
                        if (rawKws) {
                            var parts = rawKws.split(",")
                            for (var k = 0; k < parts.length; k++) {
                                var trimmed = parts[k].trim()
                                if (trimmed.length > 0 && kwsList.indexOf(trimmed) === -1) {
                                    kwsList.push(trimmed)
                                }
                            }
                        }

                        outProds.push({
                            "id": item.id,
                            "name": item.name,
                            "keyword": rawKws,
                            "keywords": kwsList,
                            "layers": ["Primer", "White", "CMYK"],
                            "choke_white_px": item.choke_white_px,
                            "choke_primer_px": 0,
                            "hotfolders": item.hotfolders
                        })
                    }

                    var folderFiltersRaw = folderFilterInput.text.trim()
                    var folderFiltersList = folderFiltersRaw ? folderFiltersRaw.split(",").map(function(s){return s.trim()}).filter(function(s){return s.length > 0}) : []

                    var newCfg = {
                        "inbox_folder": inboxInput.text,
                        "folder_filter_keywords": folderFiltersList,
                        "staging_folder": stagingInput.text,
                        "auto_pipeline": autoPipelineCheckBox.checked,
                        "scan_interval_sec": 15,
                        "products": outProds
                    }
                    printflowController.saveConfigJson(JSON.stringify(newCfg))
                    statusMsg.text = "Išsaugota!"
                    configDialog.close()
                }
                background: Rectangle { color: "#f43f5e"; radius: 6 }
                contentItem: Text { text: "💾 Išsaugoti Pakeitimus"; color: "#ffffff"; font.bold: true; font.pixelSize: 12 }
            }
        }
    }
}
