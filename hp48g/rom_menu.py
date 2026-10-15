"""Recognize native framed choice lists without interpreting their text."""
from dataclasses import dataclass

# The ROM's inverse-video OK soft key, 21 pixels by seven rows.
OK_KEY=(2097151,2067327,2075391,2075135,2075391,2067327,2097151)

@dataclass(frozen=True)
class ChoiceList:
    left:int
    top:int
    right:int
    first_y:int
    rows:int
    selected:int

    def row_at(self,x,y):
        row=int((y-self.first_y)//9)
        return row if self.left+1<x<self.right and self.first_y<=y<self.first_y+9*self.rows and 0<=row<self.rows else None


def choice_list(pixels):
    """Require an OK key, a complete frame and a full-width selection band."""
    if len(pixels)!=1088:return None
    def on(x,y):return bool(pixels[y*17+x//8]&(128>>(x%8)))
    if tuple(sum(on(x,y)<<(130-x) for x in range(110,131)) for y in range(57,64))!=OK_KEY:return None
    for top in range(0,40):
        runs=[];start=None
        for x in range(132):
            if x<131 and on(x,top):
                if start is None:start=x
            elif start is not None:
                if x-start>=50:runs.append((start,x-1))
                start=None
        for left,right in runs:
            for bottom in range(top+10,56):
                if not all(on(x,bottom) for x in range(left,right+1)):continue
                if not all(on(left,y) and on(right,y) for y in range(top,bottom+1)):continue
                # Built-in menus have no title; CHOOSE adds a title and divider.
                for first_y in (top+2,top+10):
                    height=bottom-first_y-1
                    if height<=0 or height%9:continue
                    rows=height//9
                    if not 1<=rows<=5:continue
                    for selected in range(rows):
                        y=first_y+9*selected
                        # Leave room for the scrolling arrows at the right edge.
                        columns=range(left+2,right-8)
                        if sum(on(x,y) and on(x,y+8) for x in columns)>=.9*len(columns):
                            return ChoiceList(left,top,right,first_y,rows,selected)
    return None
