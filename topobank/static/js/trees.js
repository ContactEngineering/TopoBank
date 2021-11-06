/**
 * Compoment which represents the search result tree in the select page.
 * The tree is either in "surface list" mode or "tag tree" mode.
 *
 * "surface list" mode: Shows list of surfaces and their topographies underneath
 * "tag tree" mode: Shows tree of tags (multiple levels) and underneath the surfaces
 *                  and topographies tagged with the corresponding tags
 *
 * @type {Vue}
 *
 * See https://vuejs.org/v2/examples/select2.html as example how to wrap 3rd party code into a component
 */


let search_results_vm = new Vue({
    delimiters: ['[[', ']]'],
    el: '#search-results',
    data: {
        num_items: null,
        num_pages: null,
        page_range: null,
        page_urls: null,
        num_items_on_current_page: null,
        base_urls: base_urls,
        current_page: initial_select_tab_state.current_page,
        page_size: initial_select_tab_state.page_size,
        search_term: initial_select_tab_state.search_term,
        category: initial_select_tab_state.category,
        sharing_status: initial_select_tab_state.sharing_status,
        tree_mode: initial_select_tab_state.tree_mode,
        tree_element: "#surface-tree",
        tree_mode_infos: {
            "surface list": {
                element_kind: "digital surface twins",
                hint: 'Analyze selected items by clicking on the "Analyze" button.',
            },
            "tag tree": {
                element_kind: "top level tags",
                hint: "Tags can be introduced or changed when editing meta data of surfaces and topographies.",
            }
        },
        category_filter_choices: category_filter_choices,
        sharing_status_filter_choices: sharing_status_filter_choices,
        is_loading: false,
    },
    mounted: function () {
        const vm = this;
        $(vm.tree_element)
            // init fancytree
            .fancytree({
                extensions: ["glyph", "table"],
                glyph: {
                    preset: "awesome5",
                    map: {
                        // Override distinct default icons here
                        folder: "fa-folder",
                        folderOpen: "fa-folder-open"
                    }
                },
                types: {
                    "surface": {icon: "far fa-gem", iconTooltip: "This is a digital surface twin"},
                    "topography": {icon: "far fa-file", iconTooltip: "This is a measurement"},
                    "tag": {icon: "fas fa-tag", iconTooltip: "This is a tag"},
                },
                icon: function (event, data) {
                    // data.typeInfo contains tree.types[node.type] (or {} if not found)
                    // Here we will return the specific icon for that type, or `undefined` if
                    // not type info is defined (in this case a default icon is displayed).
                    return data.typeInfo.icon;
                },
                iconTooltip: function (event, data) {
                    return data.typeInfo.iconTooltip; // set tooltip which appears when hovering an icon
                },
                table: {
                    checkboxColumnIdx: null,    // render the checkboxes into the this column index (default: nodeColumnIdx)
                    indentation: 20,            // indent every node level by these number of pixels
                    nodeColumnIdx: 0            // render node expander, icon, and title to this column (default: #0)
                },
                autoActivate: true,
                titlesTabbable: false,
                tabindex: -1,
                focusOnSelect: false,
                scrollParent: window,
                autoScroll: true,
                scrollOfs: {top: 200, bottom: 50},
                checkbox: true,
                selectMode: 2, // 'multi'
                source: {
                    url: this.search_url.toString(),  // this is a computed property, see below
                    cache: false
                },
                postProcess: function (event, data) {
                    // console.log("PostProcess: ", data);
                    vm.num_pages = data.response.num_pages;
                    vm.num_items = data.response.num_items;
                    vm.current_page = data.response.current_page;
                    vm.num_items_on_current_page = data.response.num_items_on_current_page;
                    vm.page_range = data.response.page_range;
                    vm.page_urls = data.response.page_urls;
                    vm.page_size = data.response.page_size;
                    // assuming the Ajax response contains a list of child nodes:
                    // We replace the result
                    data.result = data.response.page_results;
                    vm.is_loading = false;
                },
                select: function (event, data) {
                    const node = data.node;
                    const is_selected = node.isSelected();
                    if (node.data.urls !== undefined) {
                        if (is_selected) {
                            $.ajax({
                                type: "POST",
                                url: node.data.urls.select,
                                data: {
                                    csrfmiddlewaretoken: csrf_token
                                },
                                success: function (data, textStatus, xhr) {
                                    // console.log("Selected: " + node.data.name + " " + node.key);
                                    basket.update(data);
                                    vm.set_selected_by_key(node.key, true);
                                },
                                error: function (xhr, textStatus, errorThrown) {
                                    console.error("Could not select: " + errorThrown + " " + xhr.status + " " + xhr.responseText);
                                }
                            });
                        } else {
                            $.ajax({
                                type: "POST",
                                url: node.data.urls.unselect,
                                data: {
                                    csrfmiddlewaretoken: csrf_token
                                },
                                success: function (data, textStatus, xhr) {
                                    // console.log("Unselected: " + node.data.name + " " + node.key);
                                    basket.update(data);
                                    vm.set_selected_by_key(node.key, false);
                                },
                                error: function (xhr, textStatus, errorThrown) {
                                    console.error("Could not unselect: " + errorThrown + " " + xhr.status + " " + xhr.responseText);
                                }
                            });
                        }
                    } else {
                        console.log("No urls defined for node. Cannot pass selection to session.");
                        basket.update();
                    }
                },

                renderTitle: function (event, data) {
                    return " ";
                },

                renderColumns: function (event, data) {
                    const node = data.node;
                    const $tdList = $(node.tr).find(">td");

                    /**
                     Add special css classes to nodes depending on type
                     */

                    let extra_classes = {
                        surface: [],
                        topography: [],
                        tag: ['font-italic']
                    };

                    extra_classes[node.type].forEach(function (c) {
                        node.addClass(c);
                    });


                    /**
                     * Render columns
                     */

                    // Set column with number of measurements
                    /*
                    if (node.data.topography_count !== undefined) {
                        let topo_count_html='<div class="text-right">'+node.data.topography_count+'</div>';
                        $tdList.eq(1).html(topo_count_html);
                    }
                    */

                    // Set columns with version and authors
                    /*
                    if (node.data.version !== undefined) {
                        let version_html = node.data.version;
                        let authors_html = node.data.publication_authors;

                        if (node.data.publication_date.length > 0) {
                            version_html += " (" + node.data.publication_date +  ")";
                        }

                        version_html = "<div class='version-column'>" + version_html + "</div>";
                        $tdList
                            .eq(2)
                            .html(version_html);

                        // Also add badge for "published" to first column
                        if (node.data.version.toString().length > 0) {
                            published_html = "<span class='badge badge-info mr-1'>published</span>";
                            $tdList.eq(0).find('.fancytree-title').after(published_html);
                        }

                        $tdList
                            .eq(3)
                            .html(authors_html);

                    }
                    */

                    let description_html = "";

                    // License image
                    if (node.data.publication_license) {
                        description_html += `<img src="/static/images/cc/${node.data.publication_license}.svg" title="Dataset can be reused under the terms of a Creative Commons license." style="float:right">`;
                    }

                    // Tags
                    if (node.data.category) {
                        description_html += `<p class='badge badge-secondary mr-1'>${node.data.category_name}</p>`;
                    }

                    if (node.data.sharing_status == "own") {
                        description_html += `<p class='badge badge-info mr-1'>Created by you</p>`;
                    } else if (node.data.sharing_status == "shared") {
                        description_html += `<p class='badge badge-info mr-1'>Shared by ${node.data.creator_name}</p>`;
                    }

                    if (node.data.tags !== undefined) {
                        node.data.tags.forEach(function (tag) {
                            description_html += "<p class='badge badge-success mr-1'>" + tag + "</p>";
                        });
                    }

                    // Title
                    description_html += `<p class="select-tree-title">${node.data.name}</p>`;

                    publication_info = "";
                    if (node.data.publication_authors) {
                        publication_info += `${node.data.publication_authors} (published ${node.data.publication_date})`;
                    } else {
                        if (node.type == "surface") {
                            publication_info += `This dataset is unpublished.`;
                        }
                    }
                    if (publication_info) {
                        description_html += `<p class="select-tree-authors">${publication_info}</p>`;
                    }

                    // Set column with description
                    if (node.data.description !== undefined) {
                        const descr = node.data.description;
                        const descr_id = "description-" + node.key;
                        let first_nl_index = descr.indexOf("\n");  // -1 if no found

                        // console.log("Description: "+descr.substring(0,10)+" Key: "+node.key+" descr ID: "+descr_id+"\n");
                        description_html += "<p class='description-column'>";
                        if (first_nl_index === -1) {
                            description_html += descr;
                        } else {
                            description_html += `${descr.substring(0, first_nl_index)}...`;
                        }

                        description_html += "</p>";
                    }

                    info_footer = "";
                    if (node.data.topography_count && node.data.version) {
                        info_footer += `This is version ${node.data.version} of this digital surface twin and contains ${node.data.topography_count} measurements.`
                    } else if (node.data.version) {
                        info_footer += `This is version ${node.data.version} of this digital surface twin.`
                    } else if (node.data.topography_count) {
                        info_footer += `This digital surface twin contains ${node.data.topography_count} measurements.`
                    }
                    if (info_footer) {
                        description_html += `<p class="select-tree-info">${info_footer}</p>`
                    }

                    $tdList
                        .eq(1)
                        .html(description_html);

                    // Set columns with buttons:
                    if (node.type !== "tag") {
                        const actions_html = `
                            <div class="btn-group-vertical btn-group-sm" role="group" aria-label="Actions">
                             ${item_buttons(node.data.urls)}
                            </div>
                          `;
                        $tdList
                            .eq(2)
                            .html(actions_html);
                    }

                    // Static markup (more efficiently defined as html row template):
                    // $tdList.eq(3).html("<input type='input' value='" + "" + "'>");
                    // ...
                },
            }); // fancytree()
        vm.set_loading_indicator();
    },   // mounted()
    computed: {
        search_url: function () {
            // Returns URL object

            let url = new URL(this.base_urls[this.tree_mode]);

            // replace page_size parameter
            // ref: https://usefulangle.com/post/81/javascript-change-url-parameters
            let query_params = url.searchParams;

            query_params.set("search", this.search_term);  // empty string -> no search
            query_params.set("category", this.category);
            query_params.set("sharing_status", this.sharing_status);
            query_params.set('page_size', this.page_size);
            query_params.set('page', this.current_page);
            query_params.set('tree_mode', this.tree_mode);
            url.search = query_params.toString();
            // url = url.toString();

            console.log("Requested search URL: " + url.toString());

            return url;
        },
    },
    methods: {
        get_tree: function () {
            return $(this.tree_element).fancytree("getTree");
        },
        set_loading_indicator: function () {
            // hack: replace loading indicator from fancytree by own indicator with spinner
            let loading_node = $('tr.fancytree-statusnode-loading');
            if (loading_node) {
                loading_node.html(`
                        <td id="tree-loading-indicator" role="status">
                          <div class="h6">
                            <span id="tree-loading-spinner" class="spinner"></span>Please wait...
                          </div>
                        </td>
                    `);
                this.is_loading = true;
            }
        },
        clear_search_term: function () {
            console.log("Clearing search term..");
            this.search_term = '';
            this.reload();
        },
        reload: function () {
            /*
                Reload means: the tree must be completely reloaded,
                with currently set state of the select tab,
                except of the page number which should be 1.
             */
            const tree = this.get_tree();
            this.current_page = 1;
            console.log("Reloading tree, tree mode: " + this.tree_mode + " current page: " + this.current_page);

            tree.setOption('source', {
                url: this.search_url.toString(),
                cache: false,
            });
            this.set_loading_indicator();
        },
        load_page: function (page_no) {
            page_no = parseInt(page_no);

            if ((page_no >= 1) && (page_no <= this.page_range.length)) {
                let tree = this.get_tree();
                let page_url = new URL(this.page_urls[page_no - 1]);

                console.log("Loading page " + page_no + " from " + page_url + "..");
                tree.setOption('source', {
                    url: page_url,
                    cache: false,
                });
                this.set_loading_indicator();
            } else {
                console.warn("Cannot load page " + page_no + ", because the page number is invalid.")
            }
        },
        set_selected_by_key: function (key, selected) {
            // Set selection on all nodes with given key and
            // set it to "selected" (bool)
            const tree = this.get_tree();
            tree.findAll(function (node) {
                return node.key == key;
            }).forEach(function (node) {
                node.setSelected(selected, {noEvents: true});
                // we only want to set the checkbox here, we don't want to simulate the click
            })
        }
    }
});  // Vue

