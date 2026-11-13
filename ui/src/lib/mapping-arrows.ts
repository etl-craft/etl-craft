type Point = [number,number];
export type MappingObstacle = { x:number; y:number; width:number; height:number };

/** Port wires use the gutter between columns; bypasses stay outside transformation boxes. */
export function mappingRoute({sourceX,sourceY,targetX,targetY,lane,obstacles}: {
  sourceX:number; sourceY:number; targetX:number; targetY:number; lane:number; obstacles:MappingObstacle[];
}): Point[] {
  if(targetX<=sourceX){
    const bottom=Math.min(targetY-20,Math.max(sourceY,...obstacles.filter(box=>box.y<=sourceY).map(box=>box.y+box.height))+24+lane*12);
    return [[sourceX,sourceY],[sourceX+16+lane*12,sourceY],[sourceX+16+lane*12,bottom],[targetX-16-lane*12,bottom],[targetX-16-lane*12,targetY],[targetX,targetY]];
  }
  const margin = Math.min(20,Math.max(4,(targetX-sourceX)/4));
  const blocked = obstacles.filter(box => box.x < targetX && box.x + box.width > sourceX && box.y < Math.max(sourceY,targetY) + 8 && box.y + box.height > Math.min(sourceY,targetY) - 8);
  if (blocked.length) {
    const top = Math.min(sourceY,targetY,...blocked.map(box => box.y)) - 24 - lane * 12;
    return [[sourceX,sourceY],[sourceX+margin,sourceY],[sourceX+margin,top],[targetX-margin,top],[targetX-margin,targetY],[targetX,targetY]];
  }
  const centre = sourceX + margin + Math.max(0,targetX-sourceX-2*margin)*lane;
  return [[sourceX,sourceY],[centre,sourceY],[centre,targetY],[targetX,targetY]];
}

export function roundedMappingPath(points: Point[]): string {
  let path = `M ${points[0]![0]} ${points[0]![1]}`;
  for (let index=1;index<points.length-1;index++) {
    const [x,y] = points[index]!;
    const [px,py] = points[index-1]!;
    const [nx,ny] = points[index+1]!;
    const incoming = Math.hypot(px-x,py-y), outgoing = Math.hypot(nx-x,ny-y);
    if (!incoming || !outgoing) { path += ` L ${x} ${y}`; continue; }
    const radius = Math.min(5,incoming/2,outgoing/2);
    path += ` L ${x+(px-x)*radius/incoming} ${y+(py-y)*radius/incoming} Q ${x} ${y} ${x+(nx-x)*radius/outgoing} ${y+(ny-y)*radius/outgoing}`;
  }
  const last = points.at(-1)!;
  return `${path} L ${last[0]} ${last[1]}`;
}
