# Changelog for *TopoBank*

## 1.53.4 (To be released)

- FIX: Copy attachments and properties when publishing a DST

## 1.52.3 (2024-12-09)

- MAINT: Allow allauth headless mode

## 1.52.2 (2024-12-05)

- BUG: Ignore TypeErrors when constructing task progress

## 1.52.1 (2024-12-04)

- BUG: Correct reverse name

## 1.52.0 (2024-12-11)

- ENH: Return analysis dependencies from REST API
- ENH: Entry-point route
- ENH: Full headless mode for allauth
- BUG: Propagate dependency errors

## 1.51.0 (2024-11-25)

- ENH: Query topographies for multiple surfaces
- BUG: Return no permission if implementation does not exist

## 1.50.3 (2024-11-13)

- BUG: Allow access to user data for logged-in users
- BUG: Exclude anonymous user in search

## 1.50.2 (2024-11-13)

- BUG: Graceful handling of files without file names

## 1.50.1 (2024-11-13)

- MAINT: Removed accidental 'jedi' dependency

## 1.50.0 (2024-11-12)

- API: Objects now return an "api" field with URLs/hyperrefs to auxiliary API endpoints
  (#1108)
- API: Tags are now uniquely referred to by their name (not their id) in the API
- API: Properties returned as dictionaries (key-value pairs)
- ENH: Generic attachments for digital surface twins and measurements (#331)
- ENH: Surfaces are now returned for all tag children
- ENH: Validation of analysis parameters (#1119)
- ENH: Dependencies for analyses (#1083)
- ENH: New tag retrieve route
- ENH: Saving analysis results (protecting them from deletion)
- BUG: Avoid properties of identical name
- BUG: Tag analysis only runs on subject to which the specific user has access
- MAINT: Replace all bare `FileField`s with `Manifest` models that handle file storage,
  including upload/download logic (#1116, #1117, #1122)
- MAINT: Replace `django-guardian` with simpler authorization system (#1110)
- MAINT: Validation of instrument parameters using new pydantic metadata definition in
  `SurfaceTopography` (1.17.0 and upwards)
- TST: Refactored all tests into a new toplevel directory (#1123)

## 1.8.1 (2024-07-13)

- MAINT: Bumped dependencies to remove muSpectre and introduce muFFT
- BUG: Permission denied when analysis does not exists (right now it yields
  an internal server error)
- BUG: Skip permissions check if there are no surfaces in the subjects

## 1.8.0 (2024-05-12)

- API: `is_numerical` and `is_categorical` of Property are now properties
- ENH: Tag can report all properties of its surfaces
- MAINT: JSON serialization of JAX arrays

## 1.7.3 (2024-03-22)
 
- BUG: Fixed version discovery

## 1.7.2 (2024-03-21)

- MAINT: Changing properties Tagulous fields to `TextField`s to remove race
  condition
- MAINT: Bumped SurfaceTopography to 1.13.12

## 1.7.1 (2024-03-14)

- ENH: Report inspection task memory usage
- ENH: Report sum and max of data points when reporting analysis task memory
  usage

## 1.7.0 (2024-03-12)

- ENH: Properties as key-value pairs wi th categorical and numerical values,
  including units (#904)
- ENH: Export properties to metadata of ZIP containers (#1074)
- ENH: Tags as analysis subjects (as a replacement for surface collections)
- ENH: Import of ZIP containers from URL

## 1.6.1 (2024-01-30)

- MAINT: Updated to django-allauth >= 0.56.0
- MAINT: Don't serve from Django but redirect to S3 for published surface
  containers
- MAINT: installing pre-commit to run linting before commits

## 1.6.0 (2024-01-22)

- ENH: Return creation and modification time in API routes
- MAINT: Fix creation datetime to publication date or None if unknown (was
  set to the date of earlier migration introducing the field)

## 1.5.0 (2024-01-20)

- ENH: API route to retrieve version information
- ENH: Tracing and reporting memory usage of analysis tasks (#1060)
- ENH: Routing manager and analysis tasks to different Celery queues
- ENH: More options for filtering of sharing and publication status
- ENH: Plugins can register middlewares and context processors
- ENH: Plugin versions are now stored for each analysis (#957)
- MAINT: Updated Django to 4.2 LTS release (current 3.2 LTS will no longer be
  supported after April 2024)
- MAINT: Split UI into separate `ce_ui` app in a separate git repository
- MAINT: Split `publication` app into a separate git repository and turned it
  into an optional dependency
- MAINT: Changed django-guardian from generic to direct foreign keys
- MAINT: Enforcing PEP-8 style

## 1.4.5 (2023-12-09)

- MAINT: Allow staff users to manually force cache renewals
- MAINT: Updated SurfaceTopography to 1.12.2 (fixed SPM reader)

## 1.4.4 (2023-11-27)

- BUG: Fixed download of TXT, CSV or XLSX if one of the analyses has an error

## 1.4.3 (2023-11-26)

- BUG: Wrong base64 encoded subject when clicking analyze in topography detail view

## 1.4.2 (2023-11-26)

- MAINT: Hide elements rather than disabling them
- MAINT: Don't allow selection (batch edit) for published topographies
- MAINT: Disable edit button in permissions card when permissions cannot be edited

## 1.4.1 (2023-11-25)

- MAINT: Order measurements in digital surface twin
- BUG: Bokeh plot wrapper did not properly defined glyphs when selection is possible
- BUG: Watching data source changes in Bokeh plot wrapper

## 1.4.0 (2023-11-25)

- ENH: Batch upload (#173, #877, #905, #906, #967)
- ENH: File errors are properly reported to the user (#207)
- ENH: Button to regenerate cached properties (thumbnail, DZI, etc., #207, #789, #895)
- ENH: Added select filter options: '(shared|published) by you' (#750)
- ENH: Added creation and last modified datetime to surfaces and topographies (#1010)
- ENH: Simplified sharing, now includes ownership transfer (#706)
- BUG: Fixes related to uploading files (#223, #261, #667)
- BUG: Fixed automatic extraction of instrument parameters for some file formats
- MAINT: Removing 'DATABASE_URL' environment-var from entrypoint (#1037)
- MAINT: Bokehjs is now used for plotting line scans (#972)
- MAINT: Surface view is now largely a single-page application
- MAINT: REST API for topography handling (#173)
- MAINT: Major refactor of task handling code
- MAINT: Refactor of codebase to respect hierarchy of Django apps (#1018)
- MAINT: Cached topography properties (thumbnail, DZI, etc.) are now generated
  in a single task (#895)
- MAINT: Removed Python Bokeh dependency (#972)
- MAINT: Updated SurfaceTopography to 1.12.1

## 1.3.1 (2023-09-13)

- BUG: Return raw ids in addition to API urls (fixes analysis download)
- BUG: Limit list of analysis functions based on user permissions

## 1.3.0 (2023-09-11)

- ENH: Updated SurfaceTopography to 1.11.0
  (to add support for JPK files, but fixes for DATX files)
- MAINT: Removed usage of content type framework and generic related fields 
  for analysis subjects (#1014)
- MAINT: Moved logic for triggering of tasks (for renewing cache or analyses)
  to the models (#1017)
- MAINT: Performance optimization, e.g. prefetching of datasets (#967)

## 1.2.5 (2023-08-30)

- MAINT: Updated SurfaceTopography to 1.10.1

## 1.2.4 (2023-08-29)

- ENH: Updated SurfaceTopography to 1.10.0
  (to add support for PLUX and WSXM files, bug fixes for GWY and text)

## 1.2.3 (2023-08-28)

- ENH: Updated SurfaceTopography to 1.9.0
  (to add support for OIR and POIR files, bug fixes for SUR and LEXT)

## 1.2.2 (2023-08-21)

- MAINT: More fixes to CSRF injection

## 1.2.1 (2023-08-04)

- MAINT: Unified CSRF injection

## 1.2.0 (2023-08-01)

- ENH: DOI badge
- ENH: Sidebar instead of dropdown for notifications and user menu
- BUG: Plot collapses when switching back to web view (#1001)
- MAINT: Updated SurfaceTopography to 1.8.0
  (to add support for LEXT and DATX files, bug fixes for Mitutoyo files)
- MAINT: Only load those analysis results that the user wants to see
- MAINT: Fixed sort order of analysis downloads
- MAINT: Added django-request-profiler middleware

## 1.1.3 (2023-06-27)

- MAINT: Updated SurfaceTopography to 1.7.0
  (to add support for PLU, FRT and HFM files)

## 1.1.2 (2023-06-17)

- BUG: Fixed missing imports

## 1.1.1 (2023-06-16)

- BUG: More robust handling of complete worker failures
- MAINT: Removed dependency on unused `celery-progress` package

## 1.1.0 (2023-06-11)

- ENH: Unified single page application for analyses, including rewritten
  task status (#795, #796)
- ENH: Webpack based bundling (for the analysis app, #565, #800)
- ENH: CSV download for analyses 
- ENH: Upgrade to Vue 3
- MAINT: Converted pickled binary dictionaries to JSON fields (#573)
- MAINT: Analysis function now has permalink (#824)
- MAINT: Analysis downloads now contain instrument information (#983)
- MAINT: Analysis downloads are now in SI units (#583)
- MAINT: Additional assorted fixes (#118, #169, #499, #624, #671, #857, #897)

## 1.0.5 (2023-04-17)

- DEP: Upgrade of SurfaceTopography to 1.6.2

## 1.0.4 (2023-04-10)

- BUG: Duration of analysis object should not be a property

## 1.0.3 (2023-04-06)

- BUG: Plugin version configuration could not be saved if there is are changes
  on top of the semantic version

## 1.0.2 (2023-04-06)

- DEP: Upgrade of SurfaceTopography to 1.6.0

## 1.0.1 (2023-02-02)

- BUG: Fixed comparative analysis (#962)
- BUG: Remove copy of surface when publication fails

## 1.0.0 (2023-01-31)

- ENH: Added surface collection as analysis subject,
  now analysis functions can be implemented which 
  process a bunch of surfaces (#900)
- ENH: Added output of DOIs related to analyses
  to downloads and to display of results of analyses
  using the standard plot card view (#171)
- ENH: Also save creation time of analyses and show it 
  in the modal dialog for the tasks (#899)
- BUG: Fixed problem loading SUR files (#945)
- BUG: Fixed problem with surface collection name (#953)
- MAINT: Fined-grained enabling of tabnav tabs in settings file
- MAINT: Moved `allauth`-dependent views into `views_allauth`
- MAINT: Added license information to version information modal
- MAINT: Improved log messages of command "create_images"
- MAINT: Fixed missing "plugin.txt" for Docker image in
  production
- MAINT: Removed firefox from production's Dockerfile
- MAINT: Renamed "Sign in via ORCID" to "Sign in"
- MAINT: Default AWS access information to None
- MAINT: Added django-watchman, added celery check
- DEP: Upgrade of SurfaceTopography to 1.3.3 (#950)

## 0.92.0 (2022-12-14)

- ENH: Store bibliography (DOIs) when an analysis completes
  (#171)
- ENH: Enhanced search by also searching for names of 
  users who created digital surface twins or 
  measurements (#896)
- ENH: Also show names of creators of unpublished digital 
  surface twins and measurements in search results (#896) 
- ENH: When hovering on data point, also display measurement
  name and series name (#893)
- ENH: Made "Tasks" information more prominent and added
  possibility to renew selected analyses in the UI (#901) 
- ENH: Added management command "grant_admin_permissions"
  to give a user restricted permissions to enter 
  admin interface in order to edit organizations or check
  the state of analyses
- ENH: Enhanced management command "create_images" such that
  thumbnails and DZI files can be processed separately
  and such that only missing images are generated (#903) 
- ENH: Added link to admin interface for staff users
- ENH: Added config options PUBLICATION_ENABLED and
  PUBLICATION_DISPLAY_TAB_WITH_OWN_PUBLICATIONS which
  are True by default, but can be used to disable publications
- BUG: Fixed crashing of plots when apostrophe was used
  in the subject's name
- BUG: Fixed problem when a surface was part of an
  analysis collection
- MAINT: Close figures after generating plots from 1D
  measurements (#898)
- MAINT: Added plugin system, moved statistical analysis 
  functions and contact mechanics to individual plugins
  (topobank-statistics, topobank-contact), allows to 
  add other functionality via plugins without changing the
  main application
- MAINT: Update for package SurfaceTopography (#911,#923)
- MAINT: Update for package ContactMechanics (#872)
- MAINT: Update of django because of security issue

## 0.91.1 (2022-09-19)

- ENH: Added "Authors" tab in detail page for 
  published digital twins (#811)
- ENH: Added links to contact.engineering paper (#873) 
- BUG: Fixed missing save() statement when renewing 
  bandwidth cache
- MAINT: Security update for django, oauthlib

## 0.91.0 (2022-08-05)

- ENH: Show unreliable bandwidth in different color in 
  bandwidth plot (#825) 
- ENH: Added management command `renew_bandwidth_cache` for
  renewing bandwidth cache for all measurements which includes
  the short reliability cutoff (#880)
- BUG: Fix for parallel generation of same version numbers (#876)
- BUG: Fix for missing import when generating thumbnails (#875)
- BUG: `import_surfaces` management command now saves to database
  after updating file name and before generating squeezed file
- BUG: Fixed layout of measurement form (#878)
- MAINT: Count failed images as failed by default when using management 
  command create_images
- MAINT: Changed redis health beat check intervals
- MAINT: Removed some old template code

## 0.90.3 (2022-07-27)

- ENH: Fixed navigation bar including basket while scrolling (#779)
- BUG: Showed wrong contact mechanics details (#859)
- BUG: Fixed missing progress bars for unready analyses (#858)
- BUG: Fixed impossible return to plot tab (#863)
- BUG: Fixed missing download link for contact mechanics (#865)
- MAINT: Bumped SurfaceTopography version to 1.0

## 0.90.2 (2022-07-11)

- MAINT: Multiple performance fixes, in particular by a) reducing redundant
  SQL queries by either combining queries of filtering in memory and b)
  reducing storage requests (from the Django backend) by only loading the
  plot metadata and not the plot results when preparing the plot in the
  Django backend (#841, #847, #851)
- MAINT: Automatically create 'topobank-dev' bucket in Minio S3 of the
  development Docker environment (local.yml)
- MAINT: Security updates for django and lxml

## 0.90.1 (2022-06-27)

- MAINT: Presign in separate request when loading analysis data (#841)
- MAINT: Some optimization of SQL requests (#841)
- MAINT: Security fixes (numpy, flower)
- MAINT: No longer use of compiled numpy package because of broken wheel
- MAINT: Order of analysis result cards now matches order of chosen 
         checkboxes

## 0.90.0 (2022-05-30)

- ENH: Move plot creation from backend to frontend, speeding up
  plot creation and loading of data (#776)
- ENH: Button to hide/show certain data sources now have the 
  color of the data source next to it (#742)
- ENH: Show hierarchy of digital twins/measurements in plot (#633)
- ENH: User switchable legend for plots (#114, #296, #590, #648)
- ENH: Download plots as SVG vector graphics (#66, #589, #610, #647)
- ENH: Same digital twins/measurements have the same colors
  over all plots
- ENH: Line style is also shown in plot legend
- ENH: Added slider for line widths to plot
- ENH: Sorted functions by name (#719)
- ENH: Increased step size for maximum number of iterations in 
  contact mechanics (#809)
- ENH: Improved filenames of downloaded containers (#815)
- BUG: Fixed logscale labels (#771)
- BUG: Renamed y-label of curvature distribution to probability
  density (#350)
- BUG: Fixed step filename in plot.csv of contact data
- BUG: Plastic calculation should reset plastic displacement before each
  optimizer run (#827)
- BUG: Fixed automtatic redirection from http:// to https:// (#835) 
- MAINT: Typo on landing page (#799)
- MAINT: Some dependency updates because of security issues
- MAINT: Added temporary redirect to challenge URL

## 0.20.1 (2022-04-13)

- BUG: Added missing migration

## 0.20.0 (2022-04-13)

- BUG: Explicity make plastic system if hardness is specified (#819)
- BUG: Fix for thumbnail creation (#782)
- BUG: Fix for redundant thumbnail files (#785)
- MAINT: Removed Selenium dependency; thumbnail generation now
  uses Pillow and matplotlib (#787)
- MAINT: Store topography data and derived data (squeezed files,
  thumbnails) under a unique prefix (#801)

## 0.19.1 (2022-03-23)

- MAINT: Adjusted docker-compose file for production with Docker 
  Swarm for the use with redis, removed memcache and rabbitmq

## 0.19.0 (2022-03-23)

- ENH: Added possibility for assigning DOIs to published datasets
- ENH: Added management command 'renew_containers'
- ENH: Added switch to 'trigger_analyses' which triggers analyses
  for all topographies related to the given surfaces
- MAINT: Switched cache backend and celery broker to
  redis because of several problems with RabbitMQ and Memcached  
- MAINT: Updated django and Pillow because of CVEs

## 0.18.2 (2022-01-26)

- BUG: Fixing missing nc files in contact mechanics download
  (#786)
- BUG: Fixing contact calculations always pending after 
  triggering them manually (#788)
- BUG: Fixing unit issue in contact mechanics for measurements
  with missing data (#783)
- BUG: Now limiting size of measurements for contact mechanics
  (#784)
- BUG: Fix for memcache error (#737)
- WIP: Workaround for failing thumbnails in production (#782)
- MAINT: Updated configuration for Docker Swarm because of 
  connection failures in production ()

## 0.18.1 (2022-01-14)

- MAINT: Added missing changes in order to get running
  with new certificate and using a local Docker repository

## 0.18.0 (2022-01-14)

- ENH: Improved performance of visualization of image maps
  for displaying 2D measurements and in contact mechanics,
  now images of different details levels are calculated 
  in advance using DeepZoom (#679)
- ENH: Improved layout of surface list of Find&Select tab
  (#757)
- ENH: Improved layout of contact mechanics analyses
- ENH: Faster access to bandwidths of measurements due to
  caching in database (#421, #605)
- ENH: Creation of images for measurements can be triggered
  in background via management command (#778)
- ENH: Fixed second navigation bar (#779)
- BUG: Fixes progress meter flaws for slope-dependent 
  properties (#755)
- BUG: Fixes insufficient number of arguments for
  contact mechanics calculation (#777)
- BUG: Fixed scheduled postgres backups (#766)  
- MAINT: Avoid loading full measurement in Django Server
  which allows working with larger measurements (#769)
- MAINT: A "surface" is now called "digital surface twin"
- MAINT: Upgrade of multiple packages because of CVEs 
  (Django, celery, lxml, Pillow)

## 0.17.0 (2021-12-03)

- ENH: Detection and optional filling of missing data 
  points (#321)
- MAINT: In the download's meta.yaml, changed type of
  measurement size from tuple to list such that a 
  safe yaml loader can be used to load surfaces (#668)
- MAINT: Upgrade of reverse proxy caddy in 
  production (#767)
- MAINT: Preparations for running on Docker Swarm 

## 0.16.2 (2021-11-15)

- BUG: Fixed unicode conversion issue in OPDx reader (#761)
- BUG: Fixed wrong condition in management command
  fix_height_scale (#763)
- BUG: Missing permissions in Docker container to
  start Postgres server (#756)
- DEP: Upgrade to SurfaceTopography 0.99.1

## 0.16.1 (2021-10-25)

- BUG: Missing manifest entry problem during installation
  fixed by using another package for fontawesone 5 
  icons (#740)
- BUG: Fixes error messages in special cases of successful
  surface analysis but no successful analysis for 
  measurements (#739)
- BUG: Fixes wrong import which broke management
  command "notify_users" (#736)
- BUG: Fixes alignment of 2D PSD data to 1D PSD 
  data (#738)
- BUG: Fixes that reliability cutoff removed entire
  measurement (#747)
- BUG: Improved error message in case of server 
  error in analysis result (#746)
- DEP: Upgrade to SurfaceTopography 0.98.2 (#751)

## 0.16.0 (2021-10-18)

- ENH: Enhanced search by supporting "weblike" search 
  expressions; now the search term is interpreted as
  phrases combined by 'AND'; also logical expressions 
  with OR and - for NOT can be used; change: only 
  topographies matching the search expression are 
  displayed underneath surfaces from now on (#701)
- ENH: Reliability analysis for scanning probe data (#83)
- ENH: Scale-dependent curvature (#586)
- ENH: Added links to GitHub discussions (#722)
- ENH: Show publication authors on Find&Select page (#733)
- BUG: Scale-dependent slope is now computed using the
  brute force approach (#687)
- BUG: Fixed issue while downloading analysis results
  with stderr for y without masked values (#711)
- BUG: Missing points were not shown correctly in 
  2D plots (#699)
- BUG: Fixed height scale applied twice on import (#718)
- BUG: Fixed continuing average along x after data
  is completed (#724)
- BUG: Fixed that analyses were not recalculated
  if instrument parameters change (#728)
- BUG: Resolution value or tip radius value no longer
  mandatory when instrument type has been chosen (#705)
- MAINT: Computing of averages is handled on the
  SurfaceTopography side
- MAINT: All properties are averages to a reasonable
  number of data points (#696)
- MAINT: Decapitalized analysis function names (e.g.
  "Roughness Parameters" -> "Roughness parameters")
- MAINT: Removed error bars on analysis results
- DEP: Upgrade to Django 3.2
- DEP: Upgrade to fontawesome 5
- DEP: Upgrade to Postgres 13.4
- DEP: Upgrade to SurfaceTopography 0.98.0 (#730, #734)
- DEP: Upgrade to ContactMechanics 0.91.0
- DEP: Upgrade of several other packages
- DEP: Upgrade of sqlparse because of CVE

## 0.15.1 (2021-08-05)

- BUG: Removed unneeded form fields for instrument
  details.

## 0.15.0 (2021-08-05)

- ENH: Added entry for instrument details for
  measurements (name, instrument type and parameters);
  specific parameters are saved in JSON field
  depending on instrument type, default type
  or all measurements is 'undefined'; this data will
  be used later for reliability analysis (#620)
- ENH: Enhanced layout of XLSX files with analysis
  data for analysis functions Height/Slope/Curvature 
  Distribution, Power Spectrum, Autocorrelation, 
  Scale-dependent slope, variable bandwidth (#669)
- ENH: Added anonymous distribution with number of
  measurement uploads over users to Excel file with
  usage statistics (#693)
- ENH: Added support for SPM file format 
  as newer DI files that contain 32-bit data (#695)  
- BUG: Unified order of measurements in surface details
  and when switching between measurements (#703)
- DEP: Upgrade for several dependencies, e.g. 
  SurfaceTopography to version 0.95.1 (#697),
  upgrade of urllib3 because of a CVE
- DEP: Using now PostgreSQL also for tests because
  of JSON fields

## 0.14.0 (2021-07-01)

- ENH: Added upper and lower bound of bandwidth to 
  roughness parameter table (#677)
- ENH: Removed restriction of column width of 
  first column of roughness parameter table when
  on "Analyze" tab, added horizontal scrollbar
  instead (#560)
- ENH: Cache containers of published 
  surfaces in storage on first download, enabled
  direct download of published surfaces  by adding 
  "download/" to publication URL (#684)
- ENH: Added note how to stop animation in the 
  thumbnail gallery (#689)
- ENH: New management command to align topography
  sizes in database with reporting from 
  SurfaceTopography (#685)
- ENH: Added summary page for usage statistics with
  monthly numbers (#572), also sorted sheets now
  in descending order with the latest date first
- BUG: Fixed wrong topography for plots and 
  analysis results after changing significant
  fields like detrend_mode, was introduced with 
  0.13.0 (#590)
- BUG: Workaround for NoneType exception happened
  sometime when creating new topographies (#691)
- BUG: Fixed missing commas in BibTeX and BibLaTeX
  citations (#686)
- BUG: Fixed statistics in output when correcting 
  height scales via management command
- BUG: Fixed cryptic error messages for analyses
  on reentrant line scan, fixed display of "infinity"
  in roughness parameter table (#683)
- BUG: Improved error message if interpolation for 
  averaging fails, shows failing measurement (#681)
- BUG: Fixes in output of 'fix_height_scale' script  

## 0.13.0 (2021-06-16)

- improved performance when uploading new measurements 
  by putting jobs into background and reducing file 
  loads (#261)
- now using a squeezed datafile internally for faster 
  loading of measurements, also added management command
  for recreating those files (#605, #661)
- added publication date next to version number in 
  table on select page (#608)
- added 1D RMS curvature values for line scans and 
  maps to table with roughness parameters (#660)
- added management command 'fix_height_scale' (#678) 
- fixed failing curvature distribution for 
  uniform line scans (#663)
- fixed loading of 2D xyz files (#659, #585)  
- fixed incorrect scaling for OPD files (#675)  
- fixed internal error when analysis card for 
  contact mechanics in certain cases (#670)
- fixed count when deleting analysis functions (#657)
- fixed detrend mode option label "Remove curvature"
  to "Remove curvature and tilt" (#580)
- made display of bandwidth plot more slender for 
  surfaces with only one measurement (#630)
- upgraded to SurfaceTopography 0.94.0  
- several updates of dependencies for security reasons  
  
## 0.12.0 (2021-05-20)

- use acquisition time from data file as initial 
  value for 'measurement date' after upload, if present (#433)
- added buttons for selection and deselection of
  measurements and averages to analysis result plots (#623)
- on viewing a measurement, loading of the plot is
  now done in the background for faster page access (#597)
- fixes internal server error because of failing thumbnail
  generation (#662)
- fixes internal server error display, now show a more
  friendly page with contact link and button to go 
  back to site (#666)
- fixes server error when downloading analyses data
  for PSD for surfaces with only one measurement (#664)

## 0.11.1 (2021-05-11)

- added missing migrations

## 0.11.0 (2021-05-10)

- added "Download" button to individual surfaces to 
  "Select" page (#618)
- added "Download" button for downloading all surfaces
  related to the current selection (#642)
- make two different averages distinguishable in plot
  widgets if one is published by adding version number
  to label
- renamed analysis function "RMS Values" to "Roughness Parameters";
  added columns "from" and "symbol", added more values, show numbers 
  as decimal powers (#651, #653)
- no longer use "e" notation on plot axis, but scientific
  notation with power of 10 (#636)  
- moved labels of colorbars next to colorbars (#592)
- in analyses results for height/slope/curvature distribution,
  renamed data series from "RMS height/slope/curvature" to
  "Gaussian fit" (#641)
- changed surface container format in order to hold multiple
  data files for measurements later (#652) 
- upgrade to SurfaceTopography 0.93.0 (#643)  
- upgrade to Django 2.2.20 because of CVE
- upgrade of packages py and django-debug-toolbar because of CVEs
- fixed bug that no average curve was shown if a surface
  was selected by tag only (#632)
- fixed management command "save_default_function_kwargs" (#621)  

## 0.10.1 (2021-03-31)

- added upgrade of pip in Dockerfile so no rust is needed 
  for python package 'cryptography'

## 0.10.0 (2021-03-31)

- added surface analyses which calculates an average
  over all topographies of a surface; implemented
  for analysis functions "Power Spectrum", 
  "Autocorrelation", and "Variable Bandwidth"; 
  using a more generic analysis model in the backend 
  where not only a topography can be subject to an 
  analysis but also a surface or later other objects (#365, #602)
- added analysis function "Scale-dependent Slope",
  which also calculates an average over a surface (#403)  
- added surface name to tooltip in plots, such that
  topographies with same names can be distinguished (#567)
- added widget for choosing opacity of topographies to 
  analysis plots (#617)  
- disabled creation of example surface for new users;
  this is no longer needed since there are published
  surfaces accessible for all users (#570)
- added missing meta data for surfaces and topographies
  to surface container download; now format can contain
  multiple surfaces and licenses (#552, #614)
- added management command 'import_surfaces' which can
  be used to import surfaces containers previously downloaded
  in the web app (#601) 
- added small description on surface landing page (#574) 
- added small description for bandwidth plot (#576)
- removed plot title from many plots where not needed (#591)
- changed mail address for contact (#619)   
- uses SurfaceTopography version 0.92.0 now, 
  which returns nonuniform PSD only up to a reasonable 
  wavevector (#568)
- upgrade of Pillow, jinja, lxml, PyYAML, pygments, and django 
  because of CVEs
- also show version numbers for numpy and scipy in version
  information, also track those versions for analyses from
  now on (#600)

## 0.9.6 (2020-12-04)

- added display of license when viewing a published 
  surface (#566)
- added "Please wait" label on "Recalculate" button
  in contact mechanics when pressed
- fixed load error in some cases when searching (#543)
- fixed database error (foreign key violation) in logs 
  if an analysis has been finished, but the corresponding
  topography was already deleted in meanwhile - analysis
  is deleted then (#500)
- fixed error when too many topographies were 
  selected (#330)

## 0.9.5 (2020-12-01)

- new layout: menu bar instead of tabs, 
  selection bar below menu bar, nicer vertical pills (#532)
- added counter for total requests (#562)
- fix for RMS table in case of NaN values 
- added dummy thumbnail if thumbnail is missing
- fixed possibly wrong versions in contact mechanics 
  download (#555)
- switched back to usage of original django-tagulous (#549) 

## 0.9.4 (2020-11-23)

- added new analysis function "RMS Values" (#445)
- autoscroll in select tab which moves selected 
  row into view (#544)
- improved bandwidth plot, removed labels
  and added info box on hover with name and 
  thumbnail of the corresponding topography (#535)
- enabled custom sorting of sharing info table (#300)
- usage statistics can be sent by email (#550)  
- fixed wrong select tab state in session (#532)
- renamed button "Properties" to "View" (#537)
- on select tab, only showing first line of 
  descriptions on load, rest expandable by 
  button press (#540)
- fixed ordering by surface name on publication tab

## 0.9.3 (2020-11-12)

- fixed XSS issues
- fixed issue with "fix_permissions" management command
  (#551)

## 0.9.2 (2020-11-02)

- fixed XSS issue

## 0.9.1 (2020-11-02)

- fixed missing dependencies for plotting in production

## 0.9.0 (2020-11-02)

- users can publish their surfaces (#317, #510, #517, #525)
- anonymous session are allowed, users can browse published
  surfaces and analyses without being signed in (#164)
- added thumbnail gallery for topographies in a surface (#514)  
- added tooltip to tab headers (#512)
- adjusted dependencies to new repositories
  resulting from splitting of PyCo package (#475)
- removed plottable dependency, using now bokeh for bandwidth 
  plot (#238) 
- added terms and conditions version 2.0 (#491)
- added anonymous counts for publication and surface
  views and downloads (#511)
- Fixing display of applied boundary conditions for contact
  mechanics calculation (#519). Recalculation needed.
- Removed banner that this is a beta release (#531)  

## 0.8.3 (2020-06-26)

- fix: added missing migration for ordering of topographies 

## 0.8.2 (2020-06-26)

- fix: added missing files for tab navigation 

## 0.8.1 (2020-06-26)

Several improvements and fixes for the user interface.

- added button to basket which allows to deselect all items (#466)
- added widget for changing page size of the result table
  on the "Select" page (#469)
- saving state of filters and paging on Select tab in session (#494)  
- removed "back" buttons not needed any more because of
  tabbed interface (#473)
- simplified tab titles, fixing strange tab behavior for 
  long tab titles (#470)
- added ">>" to tab titles in order to visualize workflow (#484)  
- tab "Analyze" is only shown if an "Analyze" button has been pressed,
  added "Analyze" button to basket (#481)
- in contact mechanics plot, replaced interactive legend by
  a collapsed list of checkboxes increasing the plot area (#472)
- replaced loading indicator for tree on "Select" page (#461) 
- fixing wrong mail configuration in production (#130, #292)
- fixing overlapping pills in detail view for surfaces and
  topographies (#471)
- fixed too many tags shown in tag tree when using filtering (#465)
- fixed missing tabs when displaying terms and conditions (#474)
- fixed wrong message in analyses view if no analyses available,
  but some items have been selected (#485)
- if analyses are about to be shown which have not been triggered yet,
  these analyses are triggered automatically (#402)
- when sharing a surface, it is assured that analyses for the standard arguments
  of all automatic functions are available for the user the surface is
  shared with (#388)
- fixed bug in management command "trigger_analyses", now also replaces
  existing analyses with other arguments than default arguments (#447)
- update to Django 2.2.13 because of security issues (#488)
- updated markdown2 dependency because of security issue (#458)

## 0.8.0 (2020-05-19)

This release mainly implements a redesign of the user interface.

- replaced links in navigation bar and breadcrumbs 
  by tabbed interface (#370, #463, #462), search page is
  now called "Select"
- search field is placed in the navigation bar, search can be
  done from everywhere (#419)
- search is done servers-side, result is shown page by page (#418, #380)
- tags can also be selected for analysis        
- removed card in detail view of topography and surface (#422)
- added simple CSV file with plot data in the ZIP archive
  when downloading data from contact mechanics calculations (#459)
- maximum number of iterations for contact mechanics calculations 
  can be specified by the user (#460)
- fixed that retriggering of analyses could result in different
  default arguments (#457)
- added management script to unify function arguments for exisiting
  analyses (#468)
- fixed different number of allowed steps for automatic and manual
  step selection in contact mechanics calculations (#455)

## 0.7.6 (2020-04-06)

- contact mechanics: added option for manual pressure selection by entering a 
  list of numbers (in addition to automatic pressure selection given the number 
  of values, #452)
- upgrade of Pillow library because of security issues (#454)

## 0.7.5 (2020-02-27)

- added help page with supported file formats, descriptions for the readers
  are defined in PyCo (#424)
- management command 'trigger_analyses' now can trigger analyses also 
  for given functions or specific analyses
- added management command 'notify_users' for sending a simple notification 
  to all users (#437)
- more consistent orientation of topography images,
  including an upgrade to PyCo 0.56.0 (#440)
- more robust when no channel name was given in data file (#441),
  this seemed to generate a lot of exceptions in production
  maybe resulting in too many database clients (#436)
- fix for wrong units of special values (mean+rms) of slope and 
  curvature distributions (#444)
- fix for problem when loading line scans without position (#446)
- upgrade to Django 2.2.10 (#439)

## 0.7.4 (2020-02-14)

- problems during loading of topographies which could already
  be loaded earlier now show error message and a mailto link
  in order to report the issue (#416)
- format detection is only done once file has been uploaded (#412)
- added collection of anonymous usage statistics in local database
  (#147, #427, #431); a non-personal overview with aggregated values per day
  can be exported via the management command "export_usage_statistics" 
- make sure there is no intermediate login page when pressing
  on colored boxes on welcome page (#423)
- upgrade to Django 2.2.9 (#417) 
- upgrade to PyCo 0.55.0 (#428), this fixes problems with
  various file format (see PyCo's changelog for details)
- fix for endless recursion on 404 responses (#367), should also
  fix problems with too many database connections (#436)
  
## 0.7.3 (2019-12-20)

- fixes wrong orientation in topography image plots (#253,#378)
- fixes internal server error with existing ibw files (#413)
- fixes white description in active row of search list (#414)

## 0.7.2 (2019-12-13)

- further improvements on the usability of the surface list (#381)
- added menu option to mark all notifications as read (#391)
- removed tabs from card headers and shifted them as tabs
  to relevant places in order to make clear which part changes
  when choosing another tab (#372) 
- replace / in sheet names before saving xlsx from analyses (#77),
  was closed already but we forgot slashes in topography names
- hide selection of topographies and series in analysis view by 
  default (#310, #404); also clip too long topography names here
- in contact plot, show for each point a small over showing 
  whether a point properly converged or not, as well as values 
  from the axes (#297, #406)
- jump to surfaces, topographies or sharing page when clicking 
  the statistics panel (#248) 
- upgraded pillow package which had security issues (#400)
- upgraded PyCo package to version 0.54.2
- fix that curvature distribution can be calculated for
  periodic surfaces (#382)
- fix for missing "is_periodic" in pipeline which made e.g. that    
  PSD couldn't be calculated nonuniform topographies (#409) 
- OPDx files can now be loaded (#325)  
- fix for topographies from HDF5 files which could't be flagged 
  as periodic (#399)   
- match aspect ratio in displacement plots (#277)
- made task information larger, topography names which cannot
  be broken down to lines are now limited by ellipsis (#252)  
- fixes color of "Recalculate" button (#405)   
- removed unneeded white space in contact mechanics' README file
- don't show "Arguments for this analysis differ" in analyses results
  if nothing is selected; instead, show an info box that no surfaces 
  and topographies have been chosen yet (#408)
   
## 0.7.1 (2019-11-22)

- added "is_periodic" flag for topographies (#347)
- added help texts explaining the asterisk in forms (#305)
- added reference to analyses' download files which user has
  uploaded a topography file (#188)
- unified "please wait" indicators when loading analysis results by AJAX (#236)
- showing notification time stamps now in local time zone
- showing now 403 page if entering a URL which tries to
  access a surface which is no longer accesible
- showing now 404 page also for topography urls which do not exist
  (before server error) 
- fixed invalid links in notifications when an object is deleted (#363)
- fixed invisible topographies in surface list when filtering for category/sharing status (#376)
- improved some visual aspects in surface list (#381, not finished yet)
 
## 0.7.0 (2019-10-23)

- surfaces and topographies can now be tagged (#52)
- hierachical tags can be used when inserting slashes in the tag name, 
  e.g. "projects/big/part_one" (#266)
- replaced view of surfaces by cards with a tree widget, either listing
  all surfaces with topographies, or listing all top level tags which build 
  the main branches of a tag tree; all entries can be searched by name,
  description and tags (#304,#266)  
- search tree can be filtered by sharing state and category (#185)   
- using checkboxes for selecting analysis functions (#271)
- failed analyses are retriggered now when requested again (#371)

## 0.6.3 (2019-10-07)

- added migrations needed for bug fix (#366)
- fixed setting of topography creator to NULL if uploading user
  is removed

## 0.6.2 (2019-10-07)

- bug fix for race conditions while managing dependency versions,
  stopped new analyses (#366)
  
## 0.6.1 (2019-09-24)

- added notifications through a "bell" symbol in the navigation bar
  (#26,#332); notifications are stored in the database and shown 
  to a logged-in user; they're triggered by these events:
   
  + a surface is shared or unshared with the current user 
  + a user gets change access to a surface
  + a shared item was edited
  + a collection of analyses, which has been manually triggered
    has been finished
  + an example surface was created on first login
           
- plotting now line scans with lines; symbols are also used
  if no more than 100 points (#312)
- internal change: analyses are now saved for every combination of topography,
  function and arguments; for each user a specific combination
  is shown; one benefit is if user selects already known parameters,
  the result is immediately there (#208)
- workaround for missing points in PSD plots (#356)   
  
  
## 0.6.0 (2019-08-09)

- fixed sheet names for XLSX download of analysis data (#39,#77)
- fixed version numbers for used dependencies, they are tracked now (#176)
- tab "Warnings" instead of "Failures", incompatible topographies
  for an analysis function is shown as information in a blue box;
  hint about translucent points are shown as warning in a yellow box;
  exceptions in analyses are now shown as error, together with a link
  which makes it easy to send a bug report as e-mail with detailed 
  information (#230)
- extended management command "trigger_analyses" such that failed
  analyses can be retriggered
- ported backend to use newer PyCo version 0.51.1 (#289),
  among other things this release allows to load HDF5 files (302) 
  and OPDX files (#325), more memory efficient caching of file
  contents 
- now shows an error message when file contents are corrupt
- updated dependencies  
  
   
## 0.5.7 (2019-07-24)

- workaround: increased limit for maximum request line (#328)
- fix for server error when uploading files with space in filename (#329)

## 0.5.6 (2019-07-23)

- changed site address for Caddy server to be just the domain name

## 0.5.5 (2019-07-23)

- fixed wrong heights in topography data, using PyCo 0.32.1 now (#295,#320)
- changed buttons in when editing topographies
  and added tooltips to chevron buttons in order to  make
  more clear how batch editing works (#262)
- showing a spinner every time a point is chosen in contact mechanics (#288)
- workaround for tooltips on multiple data points in 1D plot (#246) 

## 0.5.4 (2019-07-16)

- fix for wrong height scale in case automated unit conversion
  was applied on upload (#290), metadata of already uploaded 
  topographies (size+unit) may be wrong
- added buttons and a menu entry to directly show analyses
  for the surface/topography the user is looking at (#264)
  
## 0.5.3 (2019-07-15)

- fixes for slow PSD calculations for line scans with lots of data points,
  using PyCo 0.32.0 now (#269)
- in analysis plots, replace crosshair with inspect tool (#256,#284)
- fixes wrong messages about differing function arguments (#285,#251)
- checking now permissions when downloading data (#286)

## 0.5.2 (2019-07-12)

- workaround for slow autocorrelation computation for
  nonuniform topographies with a large number of data points
- navigation chevron buttons also in topography update form

## 0.5.1 (2019-07-11)

- cosmetic changes like e.g. harmonizing sizes and loading
  behavior of opened surface and analyses cards

## 0.5.0 (2019-07-11)

- added contact mechanics analysis and visualization (#84)
- added progress bars for analysis tasks (#202)
- old analyses for same topography and same function will 
  be deleted (#221)
- added download of contact mechanics data (#228)
- added download of surface container archive (#48)
- fixed wrong unit conversion in analysis plots (#240)
- fixed sometimes wrong target url for cancel button in 
  upload wizard (#237)

## 0.4.2 (2019-06-13)

- added missing template fragment which caused crashes in analyses view (#216)

## 0.4.1 (2019-06-12)

- allow case-insensitive search for user names (#192)
- fixes wrong task information for cards in analyses view (#209)
- empty surfaces can now be selected and edited (#214)
- fixes for image plots of topographies (#76, #213)
- workaround for crash when uploading large file (#212)
- version upgrades: celery, bokeh, caddy, gunicorn

## 0.4.0 (2019-05-28)

- more responsive surface list through AJAX calls (#203)
- added progress bar when uploading a topography file (#127)
- added statistics about shared surfaces (#196)
- improved layout of surface search results and surface detail view,
  added detail view for analyses with similar layout (#197,#204)
- added bookmarking the user who uploaded a topography (#181)
- fixed bug, that users couldn't upload topographies for shared surfaces (#205)
- fixed target for cancel button when editing surface details (#198)

## 0.3.1 (2019-05-10)

- fixes bug that analyses results were not shown for shared surfaces (#186)
- fixes bug that single topographies couldn't be selected in surface list (#190)
- in order to find user names you have to type at least 3 characters (#184)
- fixes highlighting and breadcrumb for "Sharing" page in navigation bar (#187)
- improves display of help texts in topography forms (#180)
- added truncation for too long breadcrumb items in navigation bar (#134)

## 0.3.0 (2019-05-08)

- surfaces can be shared for viewing and optionally also for changing
- user can view/select each others profiles if they collaborate, i.e. share something
- shares for a surface are listed in an extra tab
- all related shares between users are listed in a "Sharing" page accesible from top menu bar
- exisiting shares can be deleted or extended in order to allow changing a surface
- prevent duplicate topography names for same surface (fixes #91)
- topographies with angstrom units can now be display in summary plot (fixes #161)

## 0.2.0 (2019-04-24)

- added category to surfaces (experimental/simulated/dummy data, #145)
- show units to users even if they cannot be changed (#149)
- added widgets for picking measurement dates (#141)
- in surface summary, sort bandwidth bars by lower bound (#85)
- added statistics on welcome page (#148)
- other bug fixes: #98

## 0.1 (2019-04-17)

- login via ORCID
- creation of surfaces with metadata
- uploading topography measurements for a surface together with metadata
- example surface with test data for new users
- zoom into topography surfaces or line scan plots
- automated analyses for topographies and line scans: 
  height/slope/curvature distribution, power spectrum, autocorrelation
- compare analysis results by stitching plots
- download of analysis results as png, xlsx, or text file
- ask user for terms and conditions, also optional terms are possible
- storage of topography files on S3 backend

