# ~/src/ats_mesh/adapters/__init__.py

from ats_mesh.adapters.bespoke.apple import Apple
from ats_mesh.adapters.bespoke.atlassian import Atlassian
from ats_mesh.adapters.bespoke.docusign import Docusign
from ats_mesh.adapters.bespoke.ibm import IBM
from ats_mesh.adapters.paginated.oracle import Oracle
from ats_mesh.adapters.paginated.workday import Workday
from ats_mesh.adapters.standard.ashby import Ashby
from ats_mesh.adapters.standard.greenhouse import Greenhouse
from ats_mesh.adapters.standard.lever import Lever
from ats_mesh.adapters.standard.smartrecruiters import SmartRecruiters

ADAPTERS = {
    "greenhouse": Greenhouse,
    "ashby": Ashby,
    "lever": Lever,
    "workday": Workday,
    "oracle": Oracle,
    "smartrecruiters": SmartRecruiters,
    "atlassian": Atlassian,
    "docusign": Docusign,
    "ibm": IBM,
    "apple": Apple,
}
