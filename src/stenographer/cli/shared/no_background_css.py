# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared transparent styles for the hub and live Textual apps."""

NO_BACKGROUND_CSS = """
Screen {
    background: transparent;
    color: ansi_default;
    scrollbar-size: 1 1;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
    scrollbar-corner-color: transparent;
}
ModalScreen {
    background: transparent;
    scrollbar-size: 1 1;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
    scrollbar-corner-color: transparent;
}
Screen > .screen--selection {
    background: transparent;
    color: #5fd7ff;
    text-style: bold;
}
Header, HeaderIcon, HeaderClock, HeaderTitle,
Footer, FooterKey, FooterLabel, Tooltip {
    background: transparent;
    color: ansi_default;
}
ScrollView, VerticalScroll, HorizontalScroll {
    background: transparent;
    background-tint: transparent;
    scrollbar-size: 1 1;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
    scrollbar-color: #5fd7ff;
    scrollbar-color-hover: #5fd7ff;
    scrollbar-color-active: #5fd7ff;
    scrollbar-corner-color: transparent;
}
HeaderIcon:hover, HeaderClock:hover, FooterKey:hover {
    background: transparent;
    background-tint: transparent;
}
FooterKey .footer-key--key,
FooterKey .footer-key--description {
    background: transparent;
}
ScrollBar {
    background: transparent;
}
DataTable {
    background: transparent;
    background-tint: transparent;
    color: ansi_default;
}
DataTable > .datatable--header,
DataTable > .datatable--fixed,
DataTable > .datatable--even-row,
DataTable > .datatable--odd-row,
DataTable > .datatable--cursor,
DataTable > .datatable--fixed-cursor,
DataTable > .datatable--header-cursor,
DataTable > .datatable--header-hover,
DataTable > .datatable--hover {
    background: transparent;
    background-tint: transparent;
}
DataTable.datatable--fixed-cursor,
DataTable:focus,
DataTable:focus > .datatable--header,
DataTable:ansi > .datatable--header,
DataTable:dark > .datatable--even-row,
DataTable:focus > .datatable--cursor,
DataTable:focus > .datatable--fixed-cursor,
DataTable:focus > .datatable--header-cursor {
    background: transparent;
    background-tint: transparent;
}
DataTable > .datatable--cursor,
DataTable > .datatable--fixed-cursor,
DataTable > .datatable--header-cursor,
DataTable:focus > .datatable--cursor,
DataTable:focus > .datatable--fixed-cursor,
DataTable:focus > .datatable--header-cursor {
    color: #5fd7ff;
    text-style: bold;
}
ListView, ListItem, OptionList, Select, SpeakerSelect, SelectCurrent,
SelectOverlay, SpeakerSelectOverlay, Input, Button {
    background: transparent;
    background-tint: transparent;
    color: ansi_default;
}
Input, SelectCurrent {
    border: round #3a4150;
}
ListView:focus {
    background: transparent;
    background-tint: transparent;
    border: round #5fd7ff;
}
ListView > ListItem.-highlight,
ListView:focus > ListItem.-highlight,
ListView > ListItem.-hovered,
OptionList > .option-list--option-highlighted,
OptionList > .option-list--option-hover,
SpeakerSelectOverlay > .option-list--option-highlighted,
SpeakerSelectOverlay > .option-list--option-hover,
OptionList:focus > .option-list--option-highlighted,
SpeakerSelectOverlay:focus > .option-list--option-highlighted {
    background: transparent;
    color: #5fd7ff;
    text-style: bold;
}
OptionList:focus, SelectCurrent:focus, SelectOverlay:focus,
SpeakerSelect:focus > SelectCurrent, SpeakerSelectOverlay:focus,
Input:focus {
    background: transparent;
    background-tint: transparent;
    border: round #5fd7ff;
}
Input > .input--cursor {
    background: transparent;
    color: #5fd7ff;
    text-style: bold underline;
}
Input > .input--selection {
    background: transparent;
    color: #5fd7ff;
    text-style: bold;
}
SpeakerSelect > SelectCurrent,
SpeakerSelect > SpeakerSelectOverlay {
    background: transparent;
    background-tint: transparent;
    color: ansi_default;
}
SpeakerSelect > SpeakerSelectOverlay {
    width: 1fr;
    display: none;
    height: auto;
    max-height: 12;
    overlay: screen;
    constrain: none inside;
    border: round #3a4150;
}
SpeakerSelect.-expanded > SpeakerSelectOverlay {
    display: block;
}
Button, Button.-style-default, Button.-style-flat,
Button.-primary, Button.-success, Button.-warning, Button.-error {
    background: transparent;
    background-tint: transparent;
    color: ansi_default;
    border: round #3a4150;
}
Button:hover, Button:focus, Button.-active,
Button.-style-default:hover, Button.-style-default:focus, Button.-style-default.-active,
Button.-style-flat:hover, Button.-style-flat:focus, Button.-style-flat.-active,
Button.-primary:hover, Button.-primary:focus, Button.-primary.-active,
Button.-success:hover, Button.-success:focus, Button.-success.-active,
Button.-warning:hover, Button.-warning:focus, Button.-warning.-active,
Button.-error:hover, Button.-error:focus, Button.-error.-active {
    background: transparent;
    background-tint: transparent;
    color: #5fd7ff;
    text-style: bold;
    border: round #5fd7ff;
}
* {
    scrollbar-size: 1 1;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
    scrollbar-corner-color: transparent;
}
"""
