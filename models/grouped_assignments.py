db.define_table('assignments',
	Field('course',db.courses),
	Field('name', 'string'),
	Field('points', 'integer'),
	Field('grade_type', 'string', default="additive", requires=IS_IN_SET(['additive','checkmark'])),
	Field('threshold', 'integer', default=1),
	format='%(name)s',
	migrate='runestone_assignments.table'
	)

def assignment_get_problems(assignment, user):
	if 'query' not in assignment or not assignment.query:
		return []
	return db(db.code.acid.like(assignment.query+"%"))(db.code.sid==user.username).select(
		db.code.ALL,
		orderby=db.code.acid|db.code.timestamp,
		distinct=db.code.acid,
		)
db.assignments.problems = Field.Method(lambda row, user: assignment_get_problems(row.assignments, user))
def assignment_set_grade(assignment, user):
	# delete the old grades; we're regrading
	db(db.grades.assignment == assignment.id)(db.grades.auth_user == user.id).delete()
	
	points = 0.0
	for prob in assignment.problems(user):
		if not prob.grade:
			continue
		points = points + prob.grade

	if assignment.grade_type == 'checkmark':
		#threshold grade
		if points >= assignment.threshold:
			points = assignment.points
		else:
			points = 0
	else:
		# they got the points they earned
		pass

	db.grades.insert(
		auth_user = user.id,
		assignment = assignment.id,
		score = points,
		)
	return points
db.assignments.grade = Field.Method(lambda row, user: assignment_set_grade(row.assignments, user))
def assignment_get_grades(assignment, section_id=None, problem=None):
	""" Return a list of users with grades for assignment (or problem) """
	if problem:
		return assignment_get_problem_grades(problem, section_id)

	if section_id:
		section_users = db((db.sections.id==db.section_users.section) & (db.auth_user.id==db.section_users.auth_user))
		users = section_users(db.auth_user.course_id == assignment.course)
		users = users(db.sections.id == section_id)
	else:
		users = db(db.auth_user.course_id == assignment.course)
	users = users.select(
		db.auth_user.ALL,
		orderby = db.auth_user.last_name,
		)
	grades = db(db.grades.assignment == assignment.id)
	grades = grades.select(db.grades.ALL)
	for u in users:
		u.grade = None
		u.comment = ""
		for g in grades:
			if g.auth_user.id == u.id:
				u.grade = g.score
	return users
def assignment_get_problem_grades(problem, section_id=None):
	code = db(db.code.sid == db.auth_user.username)
	if section_id:
		code = code((db.sections.id==db.section_users.section) & (db.auth_user.id==db.section_users.auth_user))
		code = code(db.sections.id == section_id)
	code = code(db.code.acid == problem)
	code = code.select(
		db.code.ALL,
		db.auth_user.ALL,
		orderby = db.code.sid|db.auth_user.last_name,
		distinct = db.code.sid,
		)
	users = []
	for c in code:
		u = c.auth_user
		u.grade = c.code.grade
		u.comment = c.code.comment
		users.append(u)
	return users
db.assignments.grades_get = Field.Method(lambda row, section=None, problem=None: assignment_get_grades(row.assignments, section, problem))

db.define_table('problems',
	Field('assignment',db.assignments),
	Field('acid','string'),
	migrate='runestones_problems.table',
	)

db.define_table('scores',
	Field('problem',db.problems),
	Field('auth_user',db.auth_user),
	Field('score','double'),
	Field('comment','string'),
	Field('released','boolean'),
	migrate='runestone_scores.table',
	)

db.define_table('grades',
	Field('auth_user', db.auth_user),
	Field('assignment', db.assignments),
	Field('score', 'double'),
	Field('released','boolean'),
	migrate='runestone_grades.table',
	)

db.define_table('deadlines',
	Field('assignment', db.assignments, requires=IS_IN_DB(db,'assignments.id',db.assignments._format)),
	Field('section', db.sections, requires=IS_EMPTY_OR(IS_IN_DB(db,'sections.id','%(name)s'))),
	Field('deadline','datetime'),
	migrate='runestone_deadlines.table',
	)