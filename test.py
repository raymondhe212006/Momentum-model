from multiprocessing import sharedctypes
from dask.array import diff
import numpy as np 
import pandas as pd 

def main():
    close = pd.Series([10,11,12,13,14,15,14])
    exposure = np.array([0, 0, 1, 1, 1, 1, 0])

    prev_hold=0
    enter=0
    gross_pnl=0.0
    for i in range(len(exposure)):
        if exposure[i] != prev_hold:
            if prev_hold != 0:
                gross_pnl += (close.iloc[i] - enter) * prev_hold
            if exposure[i]!=0:
                enter=close.iloc[i]
            else:
                enter=0
            prev_hold = exposure[i]

    
    exposure = pd.Series(exposure, index=close.index).shift(1).fillna(0).values  
    change_1m = close.diff()
    gross_pnl2 = np.sum(exposure * change_1m)

    print(gross_pnl)
    print(gross_pnl2)
    return 0

if __name__ == "__main__":
    exit(main())