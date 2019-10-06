# Li 2015 and Li-Daie 2016

![ALM Recordings](images/alm1.png)

This project describes the two studies:

>Nuo Li, Tsai-Wen Chen, Zengcai V. Guo, Charles R. Gerfen & Karel Svoboda. "A motor cortex circuit for motor planning and movement" (2015) Nature (https://dx.doi.org/10.1038/nature14178)

The original data are available at: https://crcns.org/data-sets/motor-cortex/alm-1

>Nuo Li, Kayvon Daie, Karel Svoboda & Shaul Druckmann. "Robust neuronal dynamics in premotor cortex during motor planning" (2016) Nature (https://dx.doi.org/10.1038/nature17643)

The original data are available at: https://crcns.org/data-sets/motor-cortex/alm-3

The data include extracellular recordings from the anterior lateral motor cortex (ALM).  The recordings were performed on mice performing tactile discrimination tasks with selective perturbations by photoinhibition, which was induced during different parts of the tasks (e.g. sample, delay, response), with varying durations, and at contra, ipsi, or bilateral ALM.  
 


## Design a DataJoint pipeline 
This repository contains the **Python 3.7** code of the DataJoint data pipeline design for this dataset, as well as scripts for data ingestions and visualization

## Conversion to NWB 2.0
This repository contains the **Python 3.7** code to convert the DataJoint pipeline into NWB 2.0 format (See https://neurodatawithoutborders.github.io/)
Each NWB file represents one recording session. The conversion script can be found [here](scripts/datajoint_to_nwb.py)

## Demonstration of the data pipeline
Data queries and usages are demonstrated in the Jupyter notebooks: [Li 2015](notebooks/Li-2015-demo.ipynb)
 and [Li-Daie 2016](notebooks/Li-Daie-2016-Demo.ipynb), where several figures from the paper are reproduced. 

## Schema Diagram
### Behavior
![ERD of the behavior data pipeline](images/behavior_erd.png)

### Ephys
![ERD of the ephys data pipeline](images/ephys_erd.png)





