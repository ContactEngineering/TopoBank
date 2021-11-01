/**
 * Helper function for visualizing 2D maps (topography, pressure, etc.) using
 * Deep Zoom Image files and OpenSeadragon.
 */

function visualizeMap(id, prefixUrl, colorBar = null) {
    $('#' + id).empty();

    $.getJSON(prefixUrl + 'dzi.dzi', function (meta) {
        meta.Image.Url = prefixUrl + 'dzi_files/';

        viewer = new OpenSeadragon.Viewer({
            id: id,
            prefixUrl: prefixUrl,
            tileSources: meta,
            showNavigator: true,
            navigatorPosition: 'TOP_LEFT',
            navigatorSizeRatio: 0.1,
            showNavigationControl: false,
            wrapHorizontal: false,
            wrapVertical: false,
            minZoomImageRatio: 0.5,
            maxZoomPixelRatio: 5.0,
        });

        // Add a scale bar
        if (meta.Image.PixelsPerMeter) {
            viewer.scalebar({
                type: OpenSeadragon.ScalebarType.MICROSCOPY,
                pixelsPerMeter: (meta.Image.PixelsPerMeter.Width + meta.Image.PixelsPerMeter.Height) / 2,
                minWidth: "75px",
                location: OpenSeadragon.ScalebarLocation.BOTTOM_LEFT,
                xOffset: 10,
                yOffset: 10,
                stayInsideImage: true,
                color: "black",
                fontColor: "black",
                backgroundColor: "rgba(255, 255, 255, 0.5)",
                fontSize: "medium",
                barThickness: 2
            });
        }

        // Add a color bar
        if (meta.Image.ColorbarRange && meta.Image.ColorbarTitle && meta.Image.Colormap) {
            var div = $('#' + colorBar);
            div.empty();
            div.append($('<div/>', {
                class: 'dzi-colorbar-title',
                html: meta.Image.ColorbarTitle
            }));
            var tickDiv = $('<div/>', {
                class: 'dzi-colorbar-column background-' + meta.Image.Colormap
            });
            var tickLabelDiv = $('<div/>', {
                class: 'dzi-colorbar-column'
            });

            mn = meta.Image.ColorbarRange.Minimum;
            mx = meta.Image.ColorbarRange.Maximum;

            tick_dist = 10 ** (Math.round(Math.log10(mx - mn)) - 1);
            nb_ticks = Math.trunc((mx - mn) / tick_dist) + 1;
            for (let i = 0; i < nb_ticks; i++) {
                v = Math.trunc(mn / tick_dist) * tick_dist + tick_dist * i;
                relpos = (mx - v) * 100 / (mx - mn);
                if (relpos > 0 && relpos < 100) {
                    tickDiv.append($('<div/>', {
                        class: 'dzi-colorbar-tick',
                        style: 'top: ' + relpos + '%;'
                    }));
                    tickLabelDiv.append($('<div/>', {
                        class: 'dzi-colorbar-text',
                        style: 'top: ' + relpos + '%;',
                        html: v.toFixed(2)
                    }));
                }
            }
            div.append(tickDiv);
            div.append(tickLabelDiv);
        }
    });
}
