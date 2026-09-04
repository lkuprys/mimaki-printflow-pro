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
        color: "#131b2e"
        radius: 12
        border.color: "#1e293b"
        border.width: 1
    }

    header: Rectangle {
        color: "#0f172a"
        height: 50
        radius: 12
        
        RowLayout {
            anchors.fill: parent
            anchors.margins: 14

            Text {
                text: "⚙️ Sistemos Nustatymai & Gaminiai"
                color: "#ffffff"
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
                    color: "#94a3b8"
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
        stagingInput.text = cfg.staging_folder || ""
        autoPipelineCheckBox.checked = !!cfg.auto_pipeline
        currentProducts = cfg.products ? JSON.parse(JSON.stringify(cfg.products)) : []
        productsModel.clear()
        for (var i = 0; i < currentProducts.length; i++) {
            productsModel.append(currentProducts[i])
        }
    }

    contentItem: ColumnLayout {
        spacing: 12

        // Inbox folder
        Rectangle {
            Layout.fillWidth: true
            height: 65
            color: "#090d16"
            radius: 8
            border.color: "#1e293b"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 4

                Text {
                    text: "📁 Bendras gamybos aplankas (Inbox / Tinklo kelias su subfolderiais):"
                    color: "#94a3b8"
                    font.bold: true
                    font.pixelSize: 11
                }

                TextField {
                    id: inboxInput
                    Layout.fillWidth: true
                    color: "#ffffff"
                    font.pixelSize: 12
                    placeholderText: "Pvz.: Z:\\GAMYBA\\UZSAKYMAI arba E:\\Projektai\\TEST\\INBOX_PRINT_FILES"
                    background: Rectangle {
                        color: "#131b2e"
                        radius: 4
                        border.color: "#334155"
                    }
                }
            }
        }

        // Staging folder & Auto Pipeline settings
        Rectangle {
            Layout.fillWidth: true
            height: 95
            color: "#090d16"
            radius: 8
            border.color: "#1e293b"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "💻 Lokalus paruoštų plokščių aplankas (Staging):"
                        color: "#94a3b8"
                        font.bold: true
                        font.pixelSize: 11
                        Layout.fillWidth: true
                    }
                    Button {
                        text: "Nustatyti į Desktop\\mimaki"
                        onClicked: stagingInput.text = "C:\\Users\\" + (Qt.platform.os === "windows" ? Qt.application.arguments[0].split("\\")[2] : "user") + "\\Desktop\\mimaki"
                        background: Rectangle { color: "#1e293b"; radius: 4; border.color: "#334155" }
                        contentItem: Text { text: "Nustatyti į Desktop\\mimaki"; color: "#38bdf8"; font.pixelSize: 10; font.bold: true }
                    }
                }

                TextField {
                    id: stagingInput
                    Layout.fillWidth: true
                    color: "#ffffff"
                    font.pixelSize: 12
                    placeholderText: "Pvz.: C:\\Users\\Vartotojas\\Desktop\\mimaki"
                    background: Rectangle {
                        color: "#131b2e"
                        radius: 4
                        border.color: "#334155"
                    }
                }

                RowLayout {
                    spacing: 8
                    CheckBox {
                        id: autoPipelineCheckBox
                        text: "⚡ Įjungti nuolatinį foninį gamybos konvejerį (Auto-Pipeline)"
                        contentItem: Text {
                            text: autoPipelineCheckBox.text
                            color: "#e2e8f0"
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
                color: "#cbd5e1"
                font.bold: true
                font.pixelSize: 12
                Layout.fillWidth: true
            }

            Button {
                text: "+ Pridėti Naują Gaminį"
                onClicked: {
                    var newP = {
                        "id": "prod_" + Date.now(),
                        "name": "Naujas Gaminys",
                        "keyword": "raktas",
                        "layers": ["White", "CMYK"],
                        "choke_white_px": 1,
                        "choke_primer_px": 0,
                        "hotfolders": { "CMYK": "", "White": "", "Primer": "" }
                    }
                    productsModel.append(newP)
                }
                background: Rectangle {
                    color: "#16a34a"
                    radius: 6
                }
                contentItem: Text {
                    text: "+ Pridėti Naują Gaminį"
                    color: "#090d16"
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
                    height: 175
                    color: "#090d16"
                    radius: 8
                    border.color: "#1e293b"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6

                        // Row 1: Name & Delete
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "Pavadinimas:"; color: "#64748b"; font.pixelSize: 11 }
                            TextField {
                                id: nameField
                                Layout.fillWidth: true
                                text: model.name || ""
                                color: "#ffffff"
                                font.bold: true
                                font.pixelSize: 12
                                background: Rectangle { color: "#131b2e"; radius: 4; border.color: "#334155" }
                                onTextChanged: productsModel.setProperty(index, "name", text)
                            }
                            Button {
                                text: "Ištrinti"
                                onClicked: productsModel.remove(index)
                                background: Rectangle { color: "#451a1a"; radius: 4; border.color: "#7f1d1d" }
                                contentItem: Text { text: "Ištrinti"; color: "#f87171"; font.pixelSize: 11; font.bold: true }
                            }
                        }

                        // Row 2: Keyword & Layers
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "Raktinis žodis:"; color: "#64748b"; font.pixelSize: 11 }
                            TextField {
                                id: kwField
                                Layout.preferredWidth: 160
                                text: model.keyword || ""
                                color: "#ffffff"
                                font.pixelSize: 11
                                background: Rectangle { color: "#131b2e"; radius: 4; border.color: "#334155" }
                                onTextChanged: productsModel.setProperty(index, "keyword", text)
                            }

                            Item { Layout.fillWidth: true }

                            Text { text: "Balto Choke (px):"; color: "#64748b"; font.pixelSize: 11 }
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
                                Text { text: "CMYK HotFolder:"; color: "#475569"; font.pixelSize: 10; Layout.preferredWidth: 100 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: model.hotfolders ? (model.hotfolders.CMYK || "") : ""
                                    color: "#cbd5e1"
                                    font.pixelSize: 10
                                    background: Rectangle { color: "#131b2e"; radius: 3; border.color: "#1e293b" }
                                    onTextChanged: {
                                        var hf = model.hotfolders || {}
                                        hf.CMYK = text
                                        productsModel.setProperty(index, "hotfolders", hf)
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "White HotFolder:"; color: "#475569"; font.pixelSize: 10; Layout.preferredWidth: 100 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: model.hotfolders ? (model.hotfolders.White || "") : ""
                                    color: "#cbd5e1"
                                    font.pixelSize: 10
                                    background: Rectangle { color: "#131b2e"; radius: 3; border.color: "#1e293b" }
                                    onTextChanged: {
                                        var hf = model.hotfolders || {}
                                        hf.White = text
                                        productsModel.setProperty(index, "hotfolders", hf)
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "Primer HotFolder:"; color: "#475569"; font.pixelSize: 10; Layout.preferredWidth: 100 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: model.hotfolders ? (model.hotfolders.Primer || "") : ""
                                    color: "#cbd5e1"
                                    font.pixelSize: 10
                                    background: Rectangle { color: "#131b2e"; radius: 3; border.color: "#1e293b" }
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
        color: "#0f172a"
        height: 55
        radius: 12

        RowLayout {
            anchors.fill: parent
            anchors.margins: 12

            Text {
                id: statusMsg
                text: ""
                color: "#4ade80"
                font.pixelSize: 11
                Layout.fillWidth: true
            }

            Button {
                text: "Atšaukti"
                onClicked: configDialog.close()
                background: Rectangle { color: "#1e293b"; radius: 6 }
                contentItem: Text { text: "Atšaukti"; color: "#94a3b8"; font.bold: true; font.pixelSize: 12 }
            }

            Button {
                text: "💾 Išsaugoti Pakeitimus"
                onClicked: {
                    var outProds = []
                    for (var i = 0; i < productsModel.count; i++) {
                        var item = productsModel.get(i)
                        outProds.push({
                            "id": item.id,
                            "name": item.name,
                            "keyword": item.keyword,
                            "layers": ["Primer", "White", "CMYK"],
                            "choke_white_px": item.choke_white_px,
                            "choke_primer_px": 0,
                            "hotfolders": item.hotfolders
                        })
                    }

                    var newCfg = {
                        "inbox_folder": inboxInput.text,
                        "staging_folder": stagingInput.text,
                        "auto_pipeline": autoPipelineCheckBox.checked,
                        "scan_interval_sec": 15,
                        "products": outProds
                    }
                    printflowController.saveConfigJson(JSON.stringify(newCfg))
                    statusMsg.text = "Išsaugota!"
                    configDialog.close()
                }
                background: Rectangle { color: "#22c55e"; radius: 6 }
                contentItem: Text { text: "💾 Išsaugoti Pakeitimus"; color: "#090d16"; font.bold: true; font.pixelSize: 12 }
            }
        }
    }
}
