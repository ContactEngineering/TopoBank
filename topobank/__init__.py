# import pkg_resources
# __version__ = pkg_resources.require("topobank")[0].version

__version__ = "0.92.0"
__version_info__ = tuple(
    [
        int(num) if num.isdigit() else num
        for num in __version__.replace("-", ".", 1).split(".")
    ]
)
