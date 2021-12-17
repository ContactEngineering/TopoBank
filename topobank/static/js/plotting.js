/**
 * Helper function for plotting results with Bokeh
 */

$(document).ready(function () {
  const plot = new Bokeh.Plotting.Figure({
    height: 300,
    sizing_mode: "scale_width",
    x_axis_label: "{{ x_axis_label }}",
    y_axis_label: "{{ y_axis_label }}",
    x_axis_type: "{{ x_axis_type }}",
    y_axis_type: "{{ y_axis_type }}",
    tools: "pan,reset,save,wheel_zoom,box_zoom,hover",
    output_backend: "{{ output_backend }}"
  });

  // This should become a Bokeh theme (supported in BokehJS with 3.0 - but I cannot find the `use_theme` method)
  plot.xaxis.axis_label_text_font_style = "normal";
  plot.yaxis.axis_label_text_font_style = "normal";
  plot.xaxis.major_label_text_font_size = "16px";
  plot.yaxis.major_label_text_font_size = "16px";
  plot.xaxis.axis_label_text_font_size = "16px";
  plot.yaxis.axis_label_text_font_size = "16px";

  per_subject = {}

  {% for data_source in data_sources %}
    {
      const code = "return { x: cb_data.response.x.map(value => {{ data_source.xscale }} * value), y: cb_data.response.y.map(value => {{ data_source.yscale }} * value) };";

      const source = new Bokeh.AjaxDataSource({
        data_url: "{{ data_source.url|safe }}",
        method: "GET",
        content_type: "",
        syncable: false,
        adapter: new Bokeh.CustomJS({code})
      });
      attrs = {
        source: source,
        visible: {% if data_source.visible %} true {% else %} false {% endif %},
        color: "{{ data_source.color }}",
        alpha: {{ data_source.alpha }}
      }
      line = plot.line({field: "x"}, {field: "y"}, {...attrs, ...{width: {{ data_source.width }}}});
      {% if data_source.show_symbols %}
        symbols = plot.circle({field: "x"}, {field: "y"}, {...attrs, ...{size: 10}});
      {% else %}
        symbols = null;
      {% endif %}

      if (!("subject_{{ data_source.subject_index }}" in per_subject)) {
        per_subject.subject_{{ data_source.subject_index }} = [];
      }
      per_subject.subject_{{ data_source.subject_index }}.push({line: line, symbols: symbols});

      if ($('#card-measurements').find('#measurement-{{ data_source.subject_index }}').length == 0) {
        /* Only create new checkbox if this series has not yet shown up in the data sources */
        $('#card-measurements').prepend(`
          <div id="measurement-{{ data_source.subject_index }}" class="custom-control custom-checkbox">
            <input id="measurement-switch-{{ data_source.subject_index }}" type="checkbox" class="custom-control-input"
             style="::before{ background-color:black; }"
             checked>
            <label class="custom-control-label" for="measurement-switch-{{ data_source.subject_index }}">
              <span class="dot" style="background-color: {{ data_source.color }}"></span>
              {{ data_source.name }}
            </label>
          </div>
        `);
      }
    }
  {% endfor %}

  Bokeh.Plotting.show(plot, "#bokeh-plot");
});
