Vue.component("bokeh-plot", {
  template: `
    <div>
      <div :id='"bokeh-plot-"+uniquePrefix'></div>
      <div :id='"plot-controls-accordion-"+uniquePrefix' class="accordion plot-controls-accordion">
        <div v-for="category in categoryElements" class="card">
          <div :id='"heading-"+uniquePrefix+"-"+category.name' class="card-header plot-controls-card-header">
            <h2 class="mb-0">
              <button class="btn btn-link btn-block text-left collapsed"
                      type="button"
                      data-toggle="collapse"
                      :data-target='"#collapse-"+uniquePrefix+"-"+category.name'
                      aria-expanded="false"
                      :aria-controls='"collapse-"+uniquePrefix+"-"+category.name'>
                {{ category.title }}
              </button>
            </h2>
          </div>
          <div :id='"collapse-"+uniquePrefix+"-"+category.name'
               class="collapse"
               :aria-labelledby='"heading-"+uniquePrefix+"-"+category.name'
               :data-parent='"#plot-controls-accordion-"+uniquePrefix'>
            <div :id='"card-subjects"+uniquePrefix' class="card-body plot-controls-card-body">
              <div v-for="(element, index) in category.elements" class="custom-control custom-checkbox">
                <input :id='"switch-"+uniquePrefix+"-"+category.name+"-"+index'
                       class="custom-control-input"
                       type="checkbox"
                       :value="index"
                       v-model="category.selection">
                <label class="custom-control-label"
                       :for='"switch-"+uniquePrefix+"-"+category.name+"-"+index'>
                  <span class="dot" v-if="element.color !== null" :style='"background-color: "+element.color'></span>
                  {{ element.title }}
                </label>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <div :id='"heading-plot-options-"+uniquePrefix' class="card-header plot-controls-card-header">
            <h2 class="mb-0">
              <button class="btn btn-link btn-block text-left collapsed"
                      type="button"
                      data-toggle="collapse"
                      :data-target='"#collapse-plot-options-"+uniquePrefix'
                      aria-expanded="false"
                      :aria-controls='"collapse-plot-options-"+uniquePrefix'>
                Plot options
              </button>
            </h2>
          </div>
          <div :id='"collapse-plot-options-"+uniquePrefix'
               class="collapse"
               :aria-labelledby='"heading-plot-options-"+uniquePrefix'
               :data-parent='"#plot-controls-accordion-"+uniquePrefix'>
            <div class="card-body plot-controls-card-body">
              <div class="form-group">
                <label :for='"opacity-slider"+uniquePrefix'>Opacity of measurement lines: {{ opacity }}</label>
                <input :id='"opacity-slider"+uniquePrefix'
                       type="range"
                       min="0"
                       max="1"
                       step="0.1"
                       class="form-control-range"
                       v-model="opacity">
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  props: {
    uniquePrefix: String,  // This makes ids here unique - there should be a more elegant way to achieve this
    dataSources: Array,
    categories: Array,
    xAxisLabel: String,
    yAxisLabel: String,
    xAxisType: String,
    yAxisType: String,
    outputBackend: String,
    height: {
      type: Number,
      default: 300
    },
    sizingMode: {
      type: String,
      default: "scale_width"
    },
    tools: {
      type: Array,
      default: function() { return ["pan", "reset", "save", "wheel_zoom", "box_zoom", "hover"]; }
    }
  },
  data: function () {
    return {
      opacity: 0.4,
      categoryElements: []
    };
  },
  created: function () {
    /* For each category, create a list of unique entries */
    for (const [index, category] of this.categories.entries()) {
      let titles = new Set();
      let elements = [];
      let selection = [];

      for (const dataSource of this.dataSources) {

        if (!(category.name in dataSource)) {
          throw new Error("Key '" + category.name + "' not found in data source '" + dataSource.name + "'.");
        }

        title = dataSource[category.name];
        if (!(titles.has(title))) {
          color = index == 0 ? dataSource.color : null;  // The first category defines the color
          titles.add(title);
          elements.push({title: title, color: color});
          if (dataSource.visible) {
            selection.push(dataSource[category.name+'_index']);
          }
        }

      }

      this.categoryElements.push({
        name: category.name,
        title: category.title,
        elements: elements,
        selection: selection
      });
    }
  },
  mounted: function () {
    /* Create and style figure */
    const plot = new Bokeh.Plotting.Figure({
      height: this.height,
      sizing_mode: this.sizingMode,
      x_axis_label: this.xAxisLabel,
      y_axis_label: this.yAxisLabel,
      x_axis_type: this.xAxisType,
      y_axis_type: this.yAxisType,
      tools: this.tools,
      output_backend: this.outputBackend
    });

    /* This should become a Bokeh theme
       (supported in BokehJS with 3.0 - but I cannot find the `use_theme` method) */
    plot.xaxis.axis_label_text_font_style = "normal";
    plot.yaxis.axis_label_text_font_style = "normal";
    plot.xaxis.major_label_text_font_size = "16px";
    plot.yaxis.major_label_text_font_size = "16px";
    plot.xaxis.axis_label_text_font_size = "16px";
    plot.yaxis.axis_label_text_font_size = "16px";

    /* We iterate in reverse order because we want to the first element to appear on top of the plot */
    for (const dataSource of this.dataSources.reverse()) {
      /* Rescale all data to identical units */
      const code = "return { x: cb_data.response.x.map(value => " + dataSource.xscale + " * value), " +
        "y: cb_data.response.y.map(value => " + dataSource.yscale + " * value) };";

      /* Data source: AJAX GET request to storage system retrieving a JSON */
      const source = new Bokeh.AjaxDataSource({
        data_url: dataSource.url,
        method: "GET",
        content_type: "",
        syncable: false,
        adapter: new Bokeh.CustomJS({code})
      });

      /* Common attributes of lines and symbols */
      attrs = {
        source: source,
        visible: dataSource.visible,
        color: dataSource.color,
        alpha: dataSource.alpha
      }

      /* Create lines and symbols */
      dataSource.line = plot.line(
        {field: "x"},
        {field: "y"},
        {...attrs, ...{width: dataSource.width}}
      );
      dataSource.symbols = plot.circle(
        {field: "x"},
        {field: "y"},
        {...attrs, ...{size: 10, visible: dataSource.visible && dataSource.show_symbols}}
      );
    }

    /* Render figure to HTML div */
    Bokeh.Plotting.show(plot, "#bokeh-plot-" + this.uniquePrefix);

    this.plot = plot;
  },
  watch: {
    categoryElements: {
      handler: function () {
        this.refreshPlot();
      },
      deep: true
    },
    opacity: function () {
      this.refreshPlot();
    }
  },
  methods: {
    refreshPlot() {
      for (const dataSource of this.dataSources) {
        visible = true;
        for (const category of this.categoryElements) {
          visible = visible && category.selection.includes(dataSource[category.name+'_index']);
        }
        dataSource.line.visible = visible;
        dataSource.symbols.visible = visible && dataSource.show_symbols;
        if (dataSource.is_topography_analysis) {
          dataSource.line.alpha = this.opacity;
          dataSource.symbols.alpha = this.opacity;
        }
      }
    }
  }
});
