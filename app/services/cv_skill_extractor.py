import re
from re import Pattern

SKILL_EXTRACTION_VERSION = "taxonomy-v1"
MAX_EXTRACTED_SKILLS = 100

SKILL_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python", ("python",)),
    ("Java", ("java",)),
    ("JavaScript", ("javascript",)),
    ("TypeScript", ("typescript",)),
    ("C#", ("c#",)),
    ("C++", ("c++",)),
    ("Go", ("golang",)),
    ("Kotlin", ("kotlin",)),
    ("PHP", ("php",)),
    ("Ruby", ("ruby",)),
    ("Dart", ("dart",)),
    ("React", ("react", "react.js", "reactjs")),
    ("Next.js", ("next.js", "nextjs")),
    ("Vue.js", ("vue.js", "vuejs")),
    ("Angular", ("angular",)),
    ("HTML", ("html", "html5")),
    ("CSS", ("css", "css3")),
    ("Tailwind CSS", ("tailwind css", "tailwindcss")),
    ("Bootstrap", ("bootstrap",)),
    ("Node.js", ("node.js", "nodejs")),
    ("Express.js", ("express.js", "expressjs")),
    ("FastAPI", ("fastapi",)),
    ("Django", ("django",)),
    ("Flask", ("flask",)),
    ("Spring Boot", ("spring boot", "springboot")),
    (".NET", (".net", "asp.net", "dotnet")),
    ("Laravel", ("laravel",)),
    ("SQL", ("sql",)),
    ("PostgreSQL", ("postgresql", "postgres")),
    ("MySQL", ("mysql",)),
    ("SQLite", ("sqlite",)),
    ("MongoDB", ("mongodb", "mongo db")),
    ("Redis", ("redis",)),
    ("Elasticsearch", ("elasticsearch", "elastic search")),
    ("REST API", ("rest api", "restful api", "restful APIs")),
    ("GraphQL", ("graphql",)),
    ("Microservices", ("microservices", "microservice architecture")),
    ("Docker", ("docker",)),
    ("Kubernetes", ("kubernetes", "k8s")),
    ("Terraform", ("terraform",)),
    ("Ansible", ("ansible",)),
    ("Jenkins", ("jenkins",)),
    ("GitHub Actions", ("github actions",)),
    ("GitLab CI", ("gitlab ci",)),
    ("CI/CD", ("ci/cd", "continuous integration")),
    ("Linux", ("linux",)),
    ("Bash", ("bash", "shell scripting")),
    ("Nginx", ("nginx",)),
    ("AWS", ("aws", "amazon web services")),
    ("Azure", ("azure", "microsoft azure")),
    ("Google Cloud", ("google cloud", "gcp")),
    ("Kafka", ("kafka", "apache kafka")),
    ("RabbitMQ", ("rabbitmq", "rabbit mq")),
    ("pytest", ("pytest",)),
    ("JUnit", ("junit",)),
    ("Selenium", ("selenium",)),
    ("Playwright", ("playwright",)),
    ("Cypress", ("cypress",)),
    ("Prometheus", ("prometheus",)),
    ("Grafana", ("grafana",)),
    ("ELK Stack", ("elk stack", "elastic stack", "elk")),
    ("Git", ("git",)),
    ("Figma", ("figma",)),
)


def _compile_alias(alias: str) -> Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(alias)}"
        rf"(?![A-Za-z0-9])",
        flags=re.IGNORECASE,
    )


_SKILL_PATTERNS: tuple[
    tuple[str, tuple[Pattern[str], ...]],
    ...,
] = tuple(
    (
        canonical_name,
        tuple(_compile_alias(alias) for alias in aliases),
    )
    for canonical_name, aliases in SKILL_TAXONOMY
)

_SKILL_CONTEXT_REJECTIONS: dict[
    str,
    tuple[Pattern[str], ...],
] = {
    "Angular": (
        re.compile(
            r"angular\s+(?:"
            r"momentum|velocity|acceleration|frequency|"
            r"displacement|measurement|resolution|"
            r"diameter|position|motion|speed|coordinate|"
            r"distribution|distance"
            r")\b",
            flags=re.IGNORECASE,
        ),
    ),
}


def _is_rejected_context(
    canonical_name: str,
    text: str,
    start_position: int,
) -> bool:
    rejection_patterns = _SKILL_CONTEXT_REJECTIONS.get(
        canonical_name,
        (),
    )

    return any(pattern.match(text, start_position) is not None for pattern in rejection_patterns)


def extract_skills(text: str) -> list[str]:
    matches: list[tuple[int, int, str]] = []

    for taxonomy_index, (
        canonical_name,
        patterns,
    ) in enumerate(_SKILL_PATTERNS):
        earliest_position: int | None = None

        for pattern in patterns:
            for match in pattern.finditer(text):
                if _is_rejected_context(
                    canonical_name,
                    text,
                    match.start(),
                ):
                    continue

                if earliest_position is None or match.start() < earliest_position:
                    earliest_position = match.start()

                break

        if earliest_position is not None:
            matches.append(
                (
                    earliest_position,
                    taxonomy_index,
                    canonical_name,
                )
            )

    matches.sort(
        key=lambda match: (
            match[0],
            match[1],
        )
    )

    return [canonical_name for _, _, canonical_name in matches[:MAX_EXTRACTED_SKILLS]]
