# ~/src/ats_mesh/models.py

from dataclasses import dataclass, field


@dataclass
class JobBasic:
    """Surface-level info, taken straight from a company's job list.

    Stage 1. One list call per company, never one request per job.
    Identity of a job is (company_name, ats_job_id), see `key`.
    """

    ats: str
    company_name: str
    ats_job_id: str
    title: str
    url: str | None = None
    locations: list[str] = field(default_factory=list)
    posted: str | None = None  # When the job was first posted (oldest confimred age)

    @property
    def key(self):
        return f"{self.company_name}:{self.ats_job_id}"
