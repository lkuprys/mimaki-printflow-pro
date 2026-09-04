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
                text: "🕒 Atliktų Spaudos Užsakymų Istorija"
                color: "#ffffff"
                font.bold: true
                font.pixelSize: 15
                Layout.fillWidth: true
            }

            Button {
                text: "✕"
                onClicked: historyDialog.close()
                background: Rectangle { color: "transparent" }
                contentItem: Text { text: "✕"; color: "#94a3b8"; font.pixelSize: 16 }
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
            height: 30
            color: "#0f172a"
            radius: 4

            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                Text { text: "Laikas"; color: "#64748b"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 70 }
                Text { text: "Užsakymas / Partija"; color: "#64748b"; font.bold: true; font.pixelSize: 11; Layout.fillWidth: true }
                Text { text: "Gaminys"; color: "#64748b"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 150 }
                Text { text: "Sluoksniai"; color: "#64748b"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 120 }
                Text { text: "Būsena"; color: "#64748b"; font.bold: true; font.pixelSize: 11; Layout.preferredWidth: 80 }
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
                    color: index % 2 === 0 ? "#090d16" : "#0d1322"
                    radius: 4

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 6
                        Text { text: model.timestamp || ""; color: "#94a3b8"; font.pixelSize: 10; font.family: "Monospace"; Layout.preferredWidth: 70 }
                        Text { text: model.job_name || ""; color: "#ffffff"; font.bold: true; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                        Text { text: model.product_name || ""; color: "#38bdf8"; font.pixelSize: 11; Layout.preferredWidth: 150; elide: Text.ElideRight }
                        Text { text: model.layers ? model.layers.join(", ") : ""; color: "#cbd5e1"; font.pixelSize: 10; Layout.preferredWidth: 120 }
                        Text { text: "SPOOLINTA"; color: "#4ade80"; font.bold: true; font.pixelSize: 10; Layout.preferredWidth: 80 }
                    }
                }
            }
        }
    }
}
