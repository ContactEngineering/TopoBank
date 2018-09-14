/* Project specific Javascript goes here. */

/*
Formatting hack to get around crispy-forms unfortunate hardcoding
in helpers.FormHelper:

    if template_pack == 'bootstrap4':
        grid_colum_matcher = re.compile('\w*col-(xs|sm|md|lg|xl)-\d+\w*')
        using_grid_layout = (grid_colum_matcher.match(self.label_class) or
                             grid_colum_matcher.match(self.field_class))
        if using_grid_layout:
            items['using_grid_layout'] = True

Issues with the above approach:

1. Fragile: Assumes Bootstrap 4's API doesn't change (it does)
2. Unforgiving: Doesn't allow for any variation in template design
3. Really Unforgiving: No way to override this behavior
4. Undocumented: No mention in the documentation, or it's too hard for me to find
*/
$('.form-group').removeClass('row');


$(document).ready(function($) {
    $(".clickable-table-row").click(function() {
        window.document.location = $(this).data("href");
    });
});

/*
 * Updated scatter plot for a certain task. Continually poll task results if data not yet available.
 */
function update_scatter_plot(div) {
    console.log(div.dataset.src);
    d3.json(div.dataset.src, function(error, json) {
        if (error)
            return console.warn(error);

        console.log(json.result);

        if (json.task_state == 'pe' || json.task_state == 'st') {
            setTimeout(function() { update_scatter_plot(div); }, 1000);
        }
        else {
            var data = json.result.hist.map(function(value, index) {
               return {x: (this[index]+this[index+1])/2, y: value};
            }, json.result.bin_edges);
            var scatter_plot = new Rickshaw.Graph({
                element: div,
                width: 500,
                height: 250,
                renderer: 'lineplot',
                series: [
                    {
                        name: "Series 1",
                        color: "steelblue",
                        data: data
                    }]
            });
            scatter_plot.render();
        }
    });
}

d3.selectAll('.topobank-scatter-plot').each(function() {
    update_scatter_plot(this);
});
