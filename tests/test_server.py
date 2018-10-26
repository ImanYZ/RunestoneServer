# *****************************************
# |docname| - Tests using the web2py server
# *****************************************
# These tests start the web2py server then submit requests to it.
#
# .. contents::
#
# Imports
# =======
# These are listed in the order prescribed by `PEP 8
# <http://www.python.org/dev/peps/pep-0008/#imports>`_.
#
# Standard library
# ----------------
import sys
import time
import subprocess
from pprint import pprint
from contextlib import contextmanager
from io import open

# Third-party imports
# -------------------
import pytest
from gluon.contrib.webclient import WebClient
import gluon.shell
from py_w3c.validators.html.validator import HTMLValidator
from contextlib2 import ExitStack

# Local imports
# -------------
from run_tests import COVER_DIRS


# Utilities
# =========
# Given a dictionary, convert it to an object. For example, if ``d['one'] == 1``, then after ``do = DictToObject(d)``, ``do.one == 1``.
class DictToObject(object):
    def __init__(self, _dict):
        self.__dict__.update(_dict)


# Create a web2py controller environment. This is taken from pieces of ``gluon.shell.run``. Given ``ctl_env = web2py_controller('app_name')``, then  ``ctl_env.db`` refers to the usual DAL object for database access, ``ctl_env.request`` is an (empty) Request object, etc.
def web2py_controller(
        # The name of the aLpplication to run in, as a string.
        application):

    _env = gluon.shell.env(application, import_models=True)
    _env.update(gluon.shell.exec_pythonrc())
    return DictToObject(_env)


# Fixtures
# ========
# This fixture starts and shuts down the web2py server.
#
# Execute this `fixture <https://docs.pytest.org/en/latest/fixture.html>`_ once per `module <https://docs.pytest.org/en/latest/fixture.html#scope-sharing-a-fixture-instance-across-tests-in-a-class-module-or-session>`_.
@pytest.fixture(scope='module')
def web2py_server():
    # Start the web2py server.
    web2py_server = subprocess.Popen(
        [sys.executable, '-m', 'coverage', 'run', '--append',
         '--source=' + COVER_DIRS, 'web2py.py', '-a', 'junk_password',
         '--nogui'])
    # Wait for the server to come up. The delay varies; this is a guess.
    time.sleep(1.5)

    # After this comes the `teardown code <https://docs.pytest.org/en/latest/fixture.html#fixture-finalization-executing-teardown-code>`_.
    yield web2py_server

    # Terminate the server to give web2py time to shut down gracefully.
    web2py_server.terminate()


# Create fixture providing a web2py controller environment for a Runestone application.
@pytest.fixture
def runestone_controller():
    return web2py_controller('runestone')


# Provide acess the the Runestone database through a fixture.
@pytest.fixture
def runestone_db(runestone_controller):
    db = runestone_controller.db
    yield db
    # In case of an error, roll back the last transaction to leave the
    # database in a working state. Also, attempt to leave the database in a
    # clean state for the next test.
    db.rollback()


# Provide context managers for manipulating the Runestone database.
class _RunestoneDbTools(object):
    def __init__(self, runestone_db):
        self.db = runestone_db

    # Create a new course. It returns the course_id of the created course.
    @contextmanager
    def create_course(self,
        # The name of the course to create, as a string.
        course_name='test_course_1',
        # The start date of the course, as a string.
        term_start_date='2000-01-01',
        # The value of the ``login_required`` flag for the course.
        login_required=True):

        course_id = self.db.courses.insert(
            course_name=course_name, base_course=course_name,
            term_start_date=term_start_date,
            login_required=login_required,
        )
        self.db.commit()
        try:
            yield course_id
        finally:
            # Remove this from the database.
            del self.db.courses[course_id]
            self.db.commit()

    @contextmanager
    def add_user_to_course(self, user_id, course_id):
        user_courses_id = self.db.user_courses.insert(course_id=course_id, user_id=user_id)
        self.db.commit()
        try:
            yield user_courses_id
        finally:
            del self.db.user_courses[user_courses_id]
            self.db.commit()


    @contextmanager
    def make_instructor(self,
        # The ID of the user to make an instructor.
        user_id,
        # The ID of the course in which the user will be an instructor.
        course_id):

        course_instructor_id =  self.db.course_instructor.insert(course=course_id, instructor=user_id)
        self.db.commit()
        db = self.db
        print(db((db.course_instructor.course == course_id) &
             (db.course_instructor.instructor == user_id)
            ).count())
        try:
            yield course_instructor_id
        finally:
            # Remove this from the database.
            del self.db.course_instructor[course_instructor_id]
            self.db.commit()


# Present ``_RunestoneDbTools`` as a fixture.
@pytest.fixture
def runestone_db_tools(runestone_db):
    return _RunestoneDbTools(runestone_db)


# Create a client for accessing the Runestone server.
class _TestClient(WebClient):
    def __init__(self):
        super(_TestClient, self).__init__('http://127.0.0.1:8000/runestone/',
                                          postbacks=True)

    # Use the W3C validator to check the HTML at the given URL.
    def validate(self,
        # The relative URL to validate.
        url,
        # An optional string that, if provided, must be in the text returned by the server
        expected_string='',
        # The number of validation errors expected. If None, no validation is performed.
        expected_errors=None):

        try:
            self.get(url)
            assert self.status == 200
            if expected_string:
                assert expected_string in self.text

            if expected_errors is not None:
                vld = HTMLValidator()
                vld.validate_fragment(self.text)
                if len(vld.errors) != expected_errors:
                    print('Errors for {}: {}'.format(url, len(vld.errors)))
                    pprint(vld.errors)
                    assert False
                if vld.warnings:
                    print('Warnings for {}: {}'.format(url, len(vld.warnings)))
                    pprint(vld.warnings)

        except AssertionError:
            # Save the HTML to make fixing the errors easier. Note that ``self.text`` is already encoded as utf-8.
            with open(url.replace('/', '-') + '.html', 'wb') as f:
                f.write(self.text.replace('\r\n', '\n'))
            raise

    def logout(self):
        self.get('default/user/logout')
        assert self.status == 200

    # Always logout after a test finishes.
    def tearDown(self):
        self.logout()


# Present ``_TestClient`` as a fixure.
@pytest.fixture
def test_client(web2py_server):
    tc = _TestClient()
    yield tc
    tc.tearDown()


# This class allows creating a user inside a context manager.
class _TestUser(object):
    def __init__(self, test_client, runestone_db_tools, username, password, course_name):
        self.test_client = test_client
        self.runestone_db_tools = runestone_db_tools
        self.username = username
        self.password = password
        self.course_name = course_name

    def __enter__(self):
        # Registration doesn't work unless we're logged out.
        self.test_client.logout()
        # First get the form to read the CSRF key, so that registration will work.
        self.test_client.get('default/user/register')
        # Now, post the registration.
        self.test_client.post('default/user/register', data=dict(
            username=self.username,
            first_name='test',
            last_name='user',
            # The e-mail address must be unique.
            email=self.username + '@foo.com',
            password=self.password,
            password_two=self.password,
            # Note that ``course_id`` is (on the form) actually a course name.
            course_id=self.course_name,
            accept_tcp='on',
            donate='0',
            _next='/runestone/default/index',
            _formname='register',
        ))
        # If this fails, write the resulting HTML to a file.
        try:
            assert self.test_client.status == 200
            assert 'Course Selection' in self.test_client.text
        except AssertionError:
            with open('register.html', 'wb') as f:
                f.write(self.test_client.text)
            raise

        # Schedule this user for deletion.
        self.exit_stack_object = ExitStack()
        self.exit_stack = self.exit_stack_object.__enter__()
        self.exit_stack.callback(self._delete_user)

        # Record the ID of this course.
        db = self.runestone_db_tools.db
        self.course_id = db(db.courses.course_name == self.course_name).select(db.courses.id).first().id

        # Finally, add the user to the specified course and schedule it for deletion.
        db = self.runestone_db_tools.db
        self.user_id = db(db.auth_user.username == self.username).select(db.auth_user.id).first().id
        self.exit_stack.enter_context(self.runestone_db_tools.add_user_to_course(self.user_id, self.course_id))

        return self

    # Delete the user created by entering this context manager.
    def _delete_user(self):
        db = self.runestone_db_tools.db
        db(db.auth_user.username == self.username).delete()
        db.commit()

    def login(self):
        self.test_client.post('default/user/login', data=dict(
            username=self.username,
            password=self.password,
            _formname='login',
        ))

    def __exit__(self, exc_type, exc_value, traceback):
        self.exit_stack_object.__exit__(exc_type, exc_value, traceback)


# Present ``_TestUser`` as a fixture.
@pytest.fixture
def test_user(test_client, runestone_db_tools):
    return lambda *args, **kwargs: _TestUser(test_client, runestone_db_tools, *args, **kwargs)


# Tests
# =====
# Validate the HTML produced by various web2py pages.
@pytest.mark.parametrize('url, requires_login, expected_string, expected_errors',
[
    # The `authentication <http://web2py.com/books/default/chapter/29/09/access-control#Authentication>`_ section gives the URLs exposed by web2py. Check these.
    ('default/user/login', False, 'Login', 1),
    ('default/user/register', False, 'Registration', 1),
    ('default/user/logout', True, 'Logged out', 1),
    # One profile error is a result of removing the input field for the e-mail, but web2py still tries to label it, which is an error.
    ('default/user/profile', True, 'Profile', 2),
    ('default/user/change_password', True, 'Change password', 1),
    # Runestone doesn't support this.
    #'default/user/verify_email', False, 'Verify email', 1),
    ('default/user/retrieve_username', False, 'Retrieve username', 1),
    ('default/user/request_reset_password', False, 'Request reset password', 1),
    # This doesn't display a webpage, but instead redirects to courses.
    #('default/user/reset_password, False, 'Reset password', 1),
    ('default/user/impersonate', True, 'Impersonate', 1),
    # FIXME: This produces an exception.
    #'default/user/groups', True, 'Groups', 1),
    ('default/user/not_authorized', False, 'Not authorized', 1),
    # Returns a 404.
    #('default/user/navbar'=(False, 'xxx', 1),

    # Other pages in ``default``.
    #
    # TODO: What is this for?
    #('default/call', False, 'Not found', 0),
    # TODO: weird returned HTML. ???
    #('default/index', True, 'Course Selection', 1),

    ('default/about', False, 'About Us', 1),
    ('default/error', False, 'Error: the document does not exist', 1),
    ('default/ack', False, 'Acknowledgements', 1),
    # web2py generates invalid labels for the radio buttons in this form.
    ('default/bio', True, 'Tell Us About Yourself', 3),
    ('default/courses', True, 'Course Selection', 1),
    ('default/remove', True, 'Remove a Course', 1),
    # FIXME: This produces an exception.
    #('default/coursechooser', True, 'xxx', 1),
    # FIXME: This produces an exception.
    #('default/removecourse', True, 'xxx', 1),
    # Should work in both cases.
    ('default/reportabug', False, 'Report a Bug', 1),
    ('default/reportabug', True, 'Report a Bug', 1),
    # TODO: weird returned HTML. ???
    #('default/sendreport', True, 'Could not create issue', 1),
    ('default/terms', False, 'Terms and Conditions', 1),
    ('default/privacy', False, 'Runestone Academy Privacy Policy', 1),
    ('default/donate', False, 'Support Runestone Interactive', 1),

    # Assignments
    ('assignments/index', True, 'Student Progress for', 1),
    # FIXME: There's a duplicated id ``fb-root`` on this page.
    ('assignments/practice', True, 'Practice tool is not set up for this course yet.', 2),
    ('assignments/chooseAssignment', True, 'Assignments', 1),

    # Misc
    ('oauth/index', False, 'This page is a utility for accepting redirects from external services like Spotify or LinkedIn that use oauth.', 1),
    # FIXME: Not sure what's wrong here.
    #('admin/index', False, 'You must be registered for a course to access this page', 1),
    #('admin/index', True, 'You must be an instructor to access this page', 1),
    ('admin/doc', True, 'Runestone Help and Documentation', 1),

    ('dashboard/index', True, 'Instructor Dashboard', 1),
    ('dashboard/grades', True, 'Gradebook', 1),
    # TODO: Many other views!
])
def test_1(url, requires_login, expected_string, expected_errors, test_client,
           test_user, runestone_db_tools):
    with runestone_db_tools.create_course('test_course_1'), \
        test_user('test_user_1', 'password_1', 'test_course_1') as test_user_1:
        if requires_login:
            test_user_1.login()
        else:
            test_client.logout()
        test_client.validate(url, expected_string,
                             expected_errors)


# Test instructor-only pages.
@pytest.mark.parametrize('url, expected_string, expected_errors',
[
    # web2py-generated stuff produces two extra errors.
    ('default/bios', 'Bios', 3),
    # FIXME: The element ``<form id="editIndexRST" action="">`` in ``views/admin/admin.html`` produces the error ``Bad value \u201c\u201d for attribute \u201caction\u201d on element \u201cform\u201d: Must be non-empty.``.
    ('admin/admin', 'Manage Section', 2),
    ('admin/grading', 'assignment', 1),
    # FIXME: these raise an exception.
    #('admin/assignments', 'Assignment', 1),
    #('admin/practice', 'Choose the sections taught, so that students can practice them.', 1),
])
def test_2(url, expected_string, expected_errors, test_client,
           test_user, runestone_db_tools):
    with runestone_db_tools.create_course('test_course_1'), \
        test_user('test_user_1', 'password_1', 'test_course_1') as test_user_1, \
        test_user('test_instructor_1', 'password_1', 'test_course_1') as test_instructor_1, \
        runestone_db_tools.make_instructor(test_instructor_1.user_id, test_instructor_1.course_id):

        # Make sure that non-instructors are redirected.
        test_client.logout()
        test_client.validate(url, 'Login')
        test_user_1.login()
        test_client.validate(url, 'Insufficient privileges')
        test_client.logout()

        # Test the instructor results.
        test_instructor_1.login()
        test_client.validate(url, expected_string,
                             expected_errors)
