import { themeQuartz } from "ag-grid-community";

/* AG Grid v33+ uses the Theming API; CSS variables on a wrapper class are ignored.
   Light/dark params are selected by the `data-ag-theme-mode` attribute set on <html>. */
export const gridTheme = themeQuartz
  .withParams(
    {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: 13,
      headerFontSize: 12,
      headerFontWeight: 600,
      rowHeight: 38,
      headerHeight: 36,
      spacing: 6,
      cellHorizontalPadding: 12,
      borderRadius: 4,
      wrapperBorderRadius: 8,
      columnBorder: true,
      rowBorder: true,
      headerColumnBorder: true,
      wrapperBorder: true,
      backgroundColor: "#ffffff",
      foregroundColor: "#14181f",
      headerBackgroundColor: "#eceff3",
      headerTextColor: "#2b3240",
      borderColor: "#e3e6ea",
      rowHoverColor: "#f6f7f9",
      selectedRowBackgroundColor: "#eef1fd",
      accentColor: "#2f4bd8",
      oddRowBackgroundColor: "#ffffff",
    },
    "light"
  )
  .withParams(
    {
      backgroundColor: "#161a21",
      foregroundColor: "#e8eaee",
      headerBackgroundColor: "#222835",
      headerTextColor: "#c3c9d3",
      borderColor: "#2a303b",
      rowHoverColor: "#1c212a",
      selectedRowBackgroundColor: "#232b45",
      accentColor: "#7a8dff",
      oddRowBackgroundColor: "#161a21",
    },
    "dark"
  );
