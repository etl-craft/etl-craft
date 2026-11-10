import "./index.css";
// The presentational surface of the console, for the design-system sync.
// Components here take their data as props and do not call the API.
export { Button, type ButtonProps } from "./components/ui/button";
export { Card, CardHeader, CardTitle, CardFooter } from "./components/ui/card";
export { Table, Th, Td } from "./components/ui/table";
export { Dialog } from "./components/ui/dialog";
export { DropdownMenu, DropdownTrigger, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator } from "./components/dropdown";
export { Tabs } from "./components/tabs";
export { TagFilter } from "./components/tag-filter";
export { SplitPane } from "./components/split-pane";
export { StatusBadge, StatusMark } from "./components/status";
export { Notice, Loading, Eyebrow, PageHeader, Breadcrumbs, Pager, SettingRow } from "./components/common";
export { ConfirmDialog } from "./components/confirm-dialog";
export { KpiTile, Panel, HBars, Trend, StackedBars } from "./components/charts";
export { CsvButton } from "./components/csv-button";
export { EnvironmentBadge, EnvironmentStrip } from "./components/environment-badge";
export { FormAction, type FieldSpec } from "./components/form-action";
export { RowActions, type RowAction } from "./components/row-actions";
// Context the components above read. Wrap any page that uses them in both.
export { MemoryRouter } from "react-router-dom";
export { QueryClient, QueryClientProvider } from "@tanstack/react-query";
