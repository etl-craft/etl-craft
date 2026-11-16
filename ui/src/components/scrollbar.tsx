import * as React from "react";
import { cn } from "@/lib/utils";

type Axis = "horizontal" | "vertical";
type ScrollbarProps = {
  axis: Axis; label: string; controls: string; value: number; maximum: number;
  page: number; onChange: (value: number) => void; className?: string;
};

/** Application-painted controls share one pointer, touch and keyboard contract. */
export function Scrollbar({axis,label,controls,value,maximum,page,onChange,className}:ScrollbarProps) {
  const horizontal=axis==="horizontal";
  const track=React.useRef<HTMLDivElement>(null);
  React.useEffect(()=>{
    const element=track.current;if(!element)return;
    const wheel=(event:WheelEvent)=>{event.preventDefault();event.stopPropagation();const unit=event.deltaMode===1?16:event.deltaMode===2?page:1;onChange(Math.max(0,Math.min(maximum,value+(horizontal?(event.deltaX||event.deltaY):event.deltaY)*unit)));};
    element.addEventListener("wheel",wheel,{passive:false});
    return()=>element.removeEventListener("wheel",wheel);
  },[value,maximum,page,onChange,horizontal]);
  const drag=React.useRef<{coordinate:number;value:number}|null>(null);
  const clamp=(next:number)=>onChange(Math.max(0,Math.min(maximum,next)));
  const coordinate=(event:React.PointerEvent)=>horizontal?event.clientX:event.clientY;
  const geometry=(element:HTMLElement)=>{
    const rect=element.getBoundingClientRect();
    const length=horizontal?element.clientWidth:element.clientHeight;
    const scale=(horizontal?rect.width:rect.height)/length;
    const thumb=element.firstElementChild as HTMLElement;
    return {scale,travel:length-(horizontal?thumb.offsetWidth:thumb.offsetHeight)};
  };
  const key=(event:React.KeyboardEvent)=>{
    const delta:Record<string,number>={ArrowLeft:-40,ArrowUp:-40,ArrowRight:40,ArrowDown:40,PageUp:-page,PageDown:page};
    if(event.key!=="Home"&&event.key!=="End"&&delta[event.key]===undefined)return;
    event.preventDefault();event.stopPropagation();
    clamp(event.key==="Home"?0:event.key==="End"?maximum:value+delta[event.key]!);
  };
  return <div ref={track} role="scrollbar" tabIndex={maximum>0?0:-1} aria-label={label} aria-controls={controls} aria-orientation={axis} aria-valuemin={0} aria-valuemax={maximum} aria-valuenow={Math.max(0,Math.min(maximum,value))} aria-disabled={maximum===0} className={cn("app-scrollbar nodrag nopan",`app-scrollbar-${axis}`,className)}
    onKeyDown={key}
    onPointerDown={event=>{
      if(event.button!==0)return;
      event.preventDefault();event.stopPropagation();event.currentTarget.focus({preventScroll:true});
      if(event.target===event.currentTarget){
        const rect=event.currentTarget.firstElementChild!.getBoundingClientRect();
        clamp(value+(coordinate(event)<(horizontal?rect.left:rect.top)?-page:page));return;
      }
      drag.current={coordinate:coordinate(event),value};event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={event=>{
      if(!drag.current)return;
      event.stopPropagation();const {scale,travel}=geometry(event.currentTarget);
      if(travel>0)clamp(drag.current.value+(coordinate(event)-drag.current.coordinate)/scale/travel*maximum);
    }}
    onPointerUp={event=>{drag.current=null;if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);}}
    onLostPointerCapture={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}
    onClick={event=>event.stopPropagation()} onDoubleClick={event=>event.stopPropagation()}>
    <span aria-hidden className="app-scrollbar-thumb" style={{[horizontal?"width":"height"]:`min(100%, max(24px, ${page/(maximum+page||1)*100}%))`,[horizontal?"left":"top"]:`${maximum?value/maximum*100:0}%`,transform:horizontal?`translateX(-${maximum?value/maximum*100:0}%)`:`translateY(-${maximum?value/maximum*100:0}%)`}}/>
  </div>;
}

function scrollSize(e:HTMLDivElement) {
  return {width:e.clientWidth,height:e.clientHeight,wide:e.scrollWidth,tall:e.scrollHeight,left:e.scrollLeft,top:e.scrollTop};
}

/** Content keeps native scrolling; visible tracks are independent of browser/OS chrome. */
export function ScrollWindow({children,className,style,viewportRef,onScroll}: {
  children:React.ReactNode;className?:string;style?:React.CSSProperties;
  viewportRef?:React.RefObject<HTMLDivElement|null>;onScroll?:React.UIEventHandler<HTMLDivElement>;
}) {
  const local=React.useRef<HTMLDivElement>(null), content=React.useRef<HTMLDivElement>(null);
  const viewport=viewportRef??local;
  const id=React.useId();
  const [size,setSize]=React.useState({width:0,height:0,wide:0,tall:0,left:0,top:0});
  React.useLayoutEffect(()=>{
    const observer=new ResizeObserver(()=>{if(viewport.current)setSize(scrollSize(viewport.current));});
    if(viewport.current)observer.observe(viewport.current);
    if(content.current)observer.observe(content.current);
    return()=>observer.disconnect();
  },[viewport]);
  return <div className={cn("scroll-window",className)} style={style}>
    <div id={id} ref={viewport} className="app-scrollport nowheel nodrag nopan" onScroll={event=>{setSize(scrollSize(event.currentTarget));onScroll?.(event);}}><div ref={content} className="scroll-window-content">{children}</div></div>
    <Scrollbar axis="horizontal" label="Window horizontal scrollbar" controls={id} value={size.left} maximum={Math.max(0,size.wide-size.width)} page={size.width} onChange={left=>viewport.current?.scrollTo({left,behavior:"instant"})}/>
    <Scrollbar axis="vertical" label="Window vertical scrollbar" controls={id} value={size.top} maximum={Math.max(0,size.tall-size.height)} page={size.height} onChange={top=>viewport.current?.scrollTo({top,behavior:"instant"})}/>
    <span className="scroll-window-corner" aria-hidden/>
  </div>;
}
