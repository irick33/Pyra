import unittest
from main import Course


class CourseTests(unittest.TestCase):
    def test_progress(self):
        self.assertEqual(Course("Python", 10, 5).progress(), 0.5)

    def test_empty_course(self):
        self.assertEqual(Course("Python", 0).progress(), 0)


if __name__ == "__main__":
    unittest.main()
