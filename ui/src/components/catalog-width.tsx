import * as React from "react";
import { Button } from "@/components/ui/button";

export const CatalogWidth = React.createContext<{wide:boolean;toggle:()=>void}|null>(null);
export function CatalogWidthButton() {
  const view=React.useContext(CatalogWidth);
  return view ? <Button aria-pressed={view.wide} onClick={view.toggle}>{view.wide?"Restore tree":"Full width"}</Button>:null;
}
