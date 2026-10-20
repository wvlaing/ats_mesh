from ats_mesh.adapters.ashby import Ashby
from ats_mesh.adapters.base import Adapter
from ats_mesh.adapters.bespoke.apple import Apple
from ats_mesh.adapters.bespoke.atlassian import Atlassian
from ats_mesh.adapters.bespoke.docusign import Docusign
from ats_mesh.adapters.bespoke.ey import Ey
from ats_mesh.adapters.bespoke.ibm import IBM
from ats_mesh.adapters.bespoke.kpmg import Kpmg
from ats_mesh.adapters.greenhouse import Greenhouse
from ats_mesh.adapters.lever import Lever
from ats_mesh.adapters.oracle import Oracle
from ats_mesh.adapters.smartrecruiters import SmartRecruiters
from ats_mesh.adapters.workday import Workday

# The "ats" names used as keys in companies.json.
ADAPTERS: dict[str, type[Adapter]] = {
    "greenhouse": Greenhouse,
    "ashby": Ashby,
    "lever": Lever,
    "workday": Workday,
    "oracle": Oracle,
    "smartrecruiters": SmartRecruiters,
    "atlassian": Atlassian,
    "docusign": Docusign,
    "ey": Ey,
    "kpmg": Kpmg,
    "ibm": IBM,
    "apple": Apple,
}
