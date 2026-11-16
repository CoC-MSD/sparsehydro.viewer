# The window

The window has the same parts on every page: the navigation rail on the left (seven workspaces, <kbd>Ctrl</kbd>+
<kbd>1</kbd> to <kbd>Ctrl</kbd>+<kbd>7</kbd>), one toolbar, one status bar, and two panels that can be shown or
hidden: **Working model** (parameter sliders) and **Activity** (background jobs and the log).

## The toolbar

Left to right:

| Group | Buttons | What they do |
| --- | --- | --- |
| Project | New, Open, Save | Always available. |
| Dataset | the **Dataset** box | The dataset every page works on; switch it from any page. Its tooltip gives the site and the periods. |
| Run | Run (<kbd>F5</kbd>), Stop (<kbd>Shift</kbd>+<kbd>F5</kbd>) | Run is the page's main command, and its label says which (Import data, Detect and fit, Run calibration, Score runs, Assess). Stop cancels what the page started. |
| Chart | Pan (<kbd>P</kbd>), Zoom box (<kbd>Z</kbd>), Fit all (<kbd>F</kbd>), Auto Y, Export | Act on the page's active chart - the time series, or the map on the Sites page. Auto Y keeps the flow axis fitted to what is visible. |
| Page | changes with the page | For example period selection on Sites, Previous/Next event on Events, Knee and Load into sliders on Explore. |
| Panels | Working model, Activity | Show or hide the two panels. |

Every button has a tooltip with its shortcut. Charts zoom with the mouse wheel and pan with the middle button in
every tool.

## The status bar

From left to right: messages; the project, dataset and working model; the value under the mouse on the active chart
(time and flow, or latitude and longitude on the map); the page's own status (for example the selected event or the
number of running calibrations); and the **activity indicator** - one progress bar over every background job and
calibration. Click it to open the Activity panel, where jobs can be cancelled and the log read.

## Projects

A project is one file (`*.shproj`, an SQLite database) holding the sites, sensors, sewersheds, their attributes and
locations, the time series themselves, the models, every calibration run and the settings. The application works on
a copy in memory; **Save** writes it back in one step, so an interrupted save cannot damage the file. Projects saved
as folders by earlier versions are imported when opened, and projects with older unit hydrograph parameters are
converted once (see [Project file](../reference/project-file)).

## Themes and accessibility

**View** offers light, dark and high-contrast themes; all three meet the WCAG 2 AA contrast levels. Every control
has a name for screen readers and a tooltip where its purpose is not written on it; pass, conditional and fail are
shown with text and a symbol as well as colour, and series are told apart by line style as well as colour. All
pages can be operated from the keyboard ([shortcuts](shortcuts)). The application follows the system font size.
