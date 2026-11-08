"""Добро пожаловать в Pyra. Shift+F10 — запуск, F5 — отладка."""

from dataclasses import dataclass


@dataclass
class Course:
    name: str
    lessons: int
    completed: int = 0

    def progress(self) -> float:
        """Возвращает долю пройденных уроков от 0 до 1."""
        return self.completed / max(self.lessons, 1)


def main() -> None:
    courses = [
        Course("Основы Python", lessons=12, completed=9),
        Course("Работа с API", lessons=8, completed=3),
        Course("Классы и объекты", lessons=10, completed=5),
    ]

    print("\033[96mМоя Python-мастерская\033[0m\n")
    for course in courses:
        percent = course.progress() * 100  # Поставьте здесь breakpoint: F9
        print(f"  {course.name:<22} {percent:5.1f}%")

    print("\nПодсказки: Ctrl+Space · Документация: Ctrl+Q")
    name = input("\nКак вас зовут? ")
    print(f"Приятно познакомиться, {name}! Пора писать код.")


if __name__ == "__main__":
    main()
