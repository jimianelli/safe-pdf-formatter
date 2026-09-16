from dataclasses import dataclass


STAGES = {
    "september": "September Plan Team draft",
    "november": "November Plan Team draft",
    "council": "Council draft",
    "final": "Final",
}

FOOTERS = {
    "GOA": "NPFMC Gulf of Alaska SAFE",
    "BSAI": "NPFMC Bering Sea and Aleutian Islands SAFE",
    "AK": "NPFMC Bering Sea, Aleutian Islands and Gulf of Alaska SAFE",
    "ECO": "NPFMC Ecosystem Considerations",
    "ECON": "NPFMC Economic SAFE",
}

DISCLAIMER = (
    "This information is distributed solely for the purpose of pre-dissemination peer review under applicable information quality guidelines.\n"
    "It has not been formally disseminated by the National Marine Fisheries Service and should not be construed to represent any agency\n"
    "determination or policy."
)


@dataclass(frozen=True)
class Chapter:
    filename: str
    heading: str
    region: str


@dataclass(frozen=True)
class FormatOptions:
    year: int = 2026
    stage: str = "september"
    headers_footers: bool = True
    page_numbers: bool = True

    @property
    def meeting_label(self):
        return {
            "september": f"September {self.year} Plan Team Draft",
            "november": f"November {self.year} Plan Team Draft",
            "council": f"November {self.year} Council Draft",
            "final": f"December {self.year}",
        }[self.stage]

    @property
    def is_draft(self):
        return self.stage != "final"
