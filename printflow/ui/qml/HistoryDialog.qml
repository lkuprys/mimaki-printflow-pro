import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: historyDialog
    title: "Spaudos Istorija"
    modal: true
    focus: true
    width: Math.min(750, parent.width - 40)
    height: Math.min(500, parent.height - 40)
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
                text: "🕒 Atliktų Spaudos Užsakymų Istorija"
                color: "#1e1b4b"
                font.bold: true
                font.pixelSize: 15
                Layout.fillWidth: true
            }

            Button {
                text: "✕"
                onClicked: historyDialog.close()
                background: Rectangle { color: "transparent" }
                contentItem: Text { text: "✕"; color: "#64748b"; font.pixelSize: 16 }
            }
        }
    }

    ListModel {
        id: historyModel
    }

    function populateHistory(jsonStr) {
        historyModel.clear()
        try {
            var items = JSON.parse(jsonStr)
            for (var i = 0; i < items.length; i++) {
                historyModel.append(items[i])
            }
        } catch (e) {}
    }

    contentItem: ColumnLayout {
        spacing: 8

        // Table Header
        Rectangle {
            Layout.fillWidth: true
            height: 32
            color: "#f1f5f9"
            radius: 6

            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                Text { text: "Laikas"; color: "#475569"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 70 }
                Text { text: "Užsakymas / Partija"; color: "#475569"; font.bold: true; font.pixelSize: 11; Layout.fillWidth: true }
                Text { text: "Gaminys"; color: "#475569"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 150 }
                Text { text: "Sluoksniai"; color: "#475569"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 120 }
                Text { text: "Būsena"; color: "#475569"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 80 }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ListView {
                id: histView
                model: historyModel
                spacing: 4

                delegate: Rectangle {
                    width: histView.width
                    height: 34
                    color: index % 2 === 0 ? "#ffffff" : "#f8fafc"
                    radius: 4
                    border.color: "#f1f5f9"
                    border.width: 1

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 6
                        Text { text: model.timestamp || ""; color: "#64748b"; font.pixelSize: 10; font.family: "Monospace"; Layout.preferredWidth: 70 }
                        Text { text: model.job_name || ""; color: "#0f172a"; font.bold: true; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                        Text { text: model.product_name || ""; color: "#2563eb"; font.pixelSize: 11; Layout.preferredWidth: 150; elide: Text.ElideRight }
                        Text { text: model.layers ? model.layers.join(", ") : ""; color: "#475569"; font.pixelSize: 10; Layout.preferredWidth: 120 }
                        
                        Rectangle {
                            Layout.preferredWidth: 75
                            height: 20
                            radius: 4
                            color: "#dcfce7"
                            Text {
                                anchors.centerIn: parent
                                text: "SPOOLINTA"
                                color: "#15803d"
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
