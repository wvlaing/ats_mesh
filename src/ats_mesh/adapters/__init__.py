# ~/src/ats_mesh/adapters/__init__.py

from ats_mesh.adapters.paginated.oracle import Oracle
from ats_mesh.adapters.paginated.workday import Workday
from ats_mesh.adapters.standard.ashby import Ashby
from ats_mesh.adapters.standard.greenhouse import Greenhouse
from ats_mesh.adapters.standard.smartrecruiters import SmartRecruiters

ADAPTERS = {
    "greenhouse": Greenhouse,
    "ashby": Ashby,
    "workday": Workday,
    "oracle": Oracle,
    "smartrecruiters": SmartRecruiters,
}
