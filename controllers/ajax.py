import json
import datetime
import logging
import time
from collections import Counter
from diff_match_patch import *

logger = logging.getLogger("web2py.app.eds")
logger.setLevel(logging.DEBUG)

response.headers['Access-Control-Allow-Origin'] = '*'

def hsblog():  # Human Subjects Board Log
    setCookie = False
    if auth.user:
        sid = auth.user.username
    else:
        if request.cookies.has_key('ipuser'):
            sid = request.cookies['ipuser'].value
            setCookie = True
        else:
            sid = str(int(time.time() * 1000)) + "@" + request.client
            setCookie = True
    act = request.vars.act
    div_id = request.vars.div_id
    event = request.vars.event
    course = request.vars.course
    ts = datetime.datetime.now()

    db.useinfo.insert(sid=sid, act=act, div_id=div_id, event=event, timestamp=ts, course_id=course)
    response.headers['content-type'] = 'application/json'
    res = {'log':True}
    if setCookie:
        response.cookies['ipuser'] = sid
        response.cookies['ipuser']['expires'] = 24 * 3600 * 90
        response.cookies['ipuser']['path'] = '/'
    return json.dumps(res)

def runlog():  # Log errors and runs with code
    setCookie = False
    if auth.user:
        sid = auth.user.username
    else:
        if request.cookies.has_key('ipuser'):
            sid = request.cookies['ipuser'].value
            setCookie = True
        else:
            sid = str(int(time.time() * 1000)) + "@" + request.client
            setCookie = True
    div_id = request.vars.div_id
    course = request.vars.course
    code = request.vars.code
    ts = datetime.datetime.now()
    error_info = request.vars.errinfo
    if error_info != 'success':
        event = 'ac_error'
        act = error_info
    else:
        act = 'run'
        event = 'activecode'
    db.acerror_log.insert(sid=sid, div_id=div_id, timestamp=ts, course_id=course, code=code, emessage=error_info)
    db.useinfo.insert(sid=sid, act=act, div_id=div_id, event=event, timestamp=ts, course_id=course)
    response.headers['content-type'] = 'application/json'
    res = {'log':True}
    if setCookie:
        response.cookies['ipuser'] = sid
        response.cookies['ipuser']['expires'] = 24 * 3600 * 90
        response.cookies['ipuser']['path'] = '/'
    return json.dumps(res)


#
#  Ajax Handlers for saving and restoring active code blocks
#

def saveprog():
    user = auth.user
    if not user:
        return json.dumps(["ERROR: auth.user is not defined.  Copy your code to the clipboard and reload or logout/login"])
    course = db(db.courses.id == auth.user.course_id).select().first()

    acid = request.vars.acid
    code = request.vars.code

    now = datetime.datetime.now()

    response.headers['content-type'] = 'application/json'
    def strip_suffix(id):
        idx = id.rfind('-') - 1
        return id[:idx]
    assignment = db(db.assignments.id == db.problems.assignment)(db.problems.acid == acid).select(db.assignments.ALL).first()
    
    section_users = db((db.sections.id==db.section_users.section) & (db.auth_user.id==db.section_users.auth_user))
    section = section_users(db.auth_user.id == user.id).select(db.sections.ALL).first()
        
    if assignment:
        q = db(db.deadlines.assignment == assignment.id)
        if section:
            q = q((db.deadlines.section == section.id) | (db.deadlines.section==None))
        else:
            q = q(db.deadlines.section==None)
        dl = q.select(db.deadlines.ALL, orderby=db.deadlines.section).first()
        if dl:
            if dl.deadline < now:
                return json.dumps(["ERROR: Sorry. The deadline for this assignment has passed. The deadline was %s" % (dl.deadline)])
    try:
        db.code.insert(sid=auth.user.username,
            acid=acid, code=code,
            timestamp=datetime.datetime.now(),
            course_id=auth.user.course_id)
    except Exception as e:
        return json.dumps(["ERROR: " + str(e) + "Please copy this error and use the Report a Problem link"])

    return json.dumps([acid])



def getprog():
    """
    return the program code for a particular acid
    :Parameters:
        - `acid`: id of the active code block
        - `user`: optional identifier for the owner of the code
    :Return:
        - json object containing the source text
    """
    codetbl = db.code
    acid = request.vars.acid
    sid = request.vars.sid

    if sid:
        query = ((codetbl.sid == sid) & (codetbl.acid == acid))
    else:
        if auth.user:
            query = ((codetbl.sid == auth.user.username) & (codetbl.acid == acid))
        else:
            query = None

    res = {}
    if query:
        result = db(query)
        res['acid'] = acid
        if not result.isempty():
            r = result.select(orderby= ~codetbl.timestamp).first().code
            res['source'] = r
            if sid:
                res['sid'] = sid
        else:
            logging.debug("Did not find anything to load for %s" % sid)
    response.headers['content-type'] = 'application/json'
    return json.dumps([res])


@auth.requires_membership('instructor')
def savegrade():
    res = db(db.code.id == request.vars.id)
    if request.vars.grade:
        res.update(grade=float(request.vars.grade))
    else:
        res.update(comment=request.vars.comment)


# @auth.requires_login()
def getuser():
    response.headers['content-type'] = 'application/json'

    if  auth.user:
        res = {'email':auth.user.email, 'nick':auth.user.username}
    else:
        res = dict(redirect=auth.settings.login_url)  # ?_next=....
    logging.debug("returning login info: %s", res)
    return json.dumps([res])


def getnumonline():
    response.headers['content-type'] = 'application/json'

    try:
        query = """select count(distinct sid) from useinfo where timestamp > current_timestamp - interval '5 minutes'  """
        rows = db.executesql(query)
    except:
        rows = [[21]]

    res = {'online':rows[0][0]}
    return json.dumps([res])


def getnumusers():
    response.headers['content-type'] = 'application/json'

    query = """select count(*) from (select distinct(sid) from useinfo) as X """

    try:
        numusers = cache.disk('numusers', lambda: db.executesql(query)[0][0], time_expire=21600)
    except:
        # sometimes the DB query takes too long and is timed out - return something anyway
        numusers = 'more than 250,000'

    res = {'numusers':numusers}
    return json.dumps([res])

#
#  Ajax Handlers to save / delete and restore user highlights
#
def savehighlight():
    parentClass = request.vars.parentClass
    hrange = request.vars.range
    method = request.vars.method
    page = request.vars.page
    pageSection = request.vars.pageSection
    course = request.vars.course

    if auth.user:
        insert_id = db.user_highlights.insert(created_on=datetime.datetime.now(),
                       user_id=auth.user.id,
                       course_id=course,
                       parent_class=parentClass,
                       range=hrange,
                       chapter_url=page,
                       sub_chapter_url=pageSection,
                       method=method)
        return str(insert_id)


def deletehighlight():
    uniqueId = request.vars.uniqueId

    if uniqueId:
        db(db.user_highlights.id == uniqueId).update(is_active=0)
    else:
        print 'uniqueId is None'

def gethighlights():
    """
    return all the highlights for a given user, on a given page
    :Parameters:
        - `page`: the page to search the highlights on
        - `course`: the course to search the highlights in
    :Return:
        - json object containing a list of matching highlights
    """
    page = request.vars.page
    course = request.vars.course
    if auth.user:
        result = db((db.user_highlights.user_id == auth.user.id) &
                    (db.user_highlights.chapter_url == page) &
                    (db.user_highlights.course_id == course) &
                    (db.user_highlights.is_active == 1)).select()
        rowarray_list = []
        for row in result:
            res = {'range': row.range, 'uniqueId': row.id,
                   'parentClass': row.parent_class,
                   'pageSection': row.sub_chapter_url, 'method': row.method}
            rowarray_list.append(res)
        return json.dumps(rowarray_list)


#
#  Ajax Handlers to update and retreive the last position of the user in the course
#
def updatelastpage():
    lastPageUrl = request.vars.lastPageUrl
    lastPageHash = request.vars.lastPageHash
    lastPageChapter = request.vars.lastPageChapter
    lastPageSubchapter = request.vars.lastPageSubchapter
    lastPageScrollLocation = request.vars.lastPageScrollLocation
    course = request.vars.course
    if auth.user:
        res = db((db.user_state.user_id == auth.user.id) &
                 (db.user_state.course_id == course))
        res.update(last_page_url=lastPageUrl, last_page_hash=lastPageHash,
                   last_page_chapter=lastPageChapter,
                   last_page_subchapter=lastPageSubchapter,
                   last_page_scroll_location=lastPageScrollLocation,
                   last_page_accessed_on=datetime.datetime.now())


def getlastpage():
    course = request.vars.course
    if auth.user:
        result = db((db.user_state.user_id == auth.user.id) &
                    (db.user_state.course_id == course)
                    ).select(db.user_state.last_page_url, db.user_state.last_page_hash,
                             db.user_state.last_page_chapter,
                             db.user_state.last_page_scroll_location,
                             db.user_state.last_page_subchapter)
        rowarray_list = []
        if result:
            for row in result:
                res = {'lastPageUrl': row.last_page_url,
                       'lastPageHash': row.last_page_hash,
                       'lastPageChapter': row.last_page_chapter,
                       'lastPageSubchapter': row.last_page_subchapter,
                       'lastPageScrollLocation': row.last_page_scroll_location}
                rowarray_list.append(res)
            return json.dumps(rowarray_list)
        else:
            db.user_state.insert(user_id=auth.user.id, course_id=course)


def getCorrectStats(miscdata, event):
    sid = None
    if auth.user:
        sid = auth.user.username
    else:
        if request.cookies.has_key('ipuser'):
            sid = request.cookies['ipuser'].value

    if sid:
        course = db(db.courses.course_name == miscdata['course']).select().first()

        correctquery = '''select
(select cast(count(*) as float) from useinfo where sid='%s'
                                               and event='%s'
                                               and DATE(timestamp) >= DATE('%s')
                                               and position('correct' in act) > 0 )
/
(select cast(count(*) as float) from useinfo where sid='%s'
                                               and event='%s'
                                               and DATE(timestamp) >= DATE('%s')
) as result;
''' % (sid, event, course.term_start_date, sid, event, course.term_start_date)

        try:
            rows = db.executesql(correctquery)
            pctcorr = round(rows[0][0] * 100)
        except:
            pctcorr = 'unavailable in sqlite'
    else:
        pctcorr = 'unavailable'

    miscdata['yourpct'] = pctcorr


def getStudentResults(question):
        course = db(db.courses.id == auth.user.course_id).select(db.courses.course_name).first()

        q = db((db.useinfo.div_id == question) &
                (db.useinfo.course_id == course.course_name) &
                (db.courses.course_name == course.course_name) &
                (db.useinfo.timestamp >= db.courses.term_start_date))

        res = q.select(db.useinfo.sid, db.useinfo.act, orderby=db.useinfo.sid)

        resultList = []
        if len(res) > 0:
            currentSid = res[0].sid
            currentAnswers = []

            for row in res:
                answer = row.act.split(':')[1]

                if row.sid == currentSid:
                    currentAnswers.append(answer)
                else:
                    currentAnswers.sort()
                    resultList.append((currentSid, currentAnswers))
                    currentAnswers = [row.act.split(':')[1]]

                    currentSid = row.sid

            currentAnswers.sort()
            resultList.append((currentSid, currentAnswers))

        return resultList


def getaggregateresults():
    course = request.vars.course
    question = request.vars.div_id
    # select act, count(*) from useinfo where div_id = 'question4_2_1' group by act;
    response.headers['content-type'] = 'application/json'

    # Yes, these two things could be done as a join.  but this **may** be better for performance
    start_date = db(db.courses.course_name == course).select(db.courses.term_start_date).first().term_start_date
    count = db.useinfo.id.count()
    result = db((db.useinfo.div_id == question) &
                (db.useinfo.course_id == course) &
                (db.useinfo.timestamp >= start_date)
                ).select(db.useinfo.act, count, groupby=db.useinfo.act)

    tdata = {}
    tot = 0
    for row in result:
        tdata[row.useinfo.act] = row[count]
        tot += row[count]

    tot = float(tot)
    rdata = {}
    miscdata = {}
    correct = ""
    if tot > 0:
        for key in tdata:
            l = key.split(':')
            try:
                answer = l[1]
                if 'correct' in key:
                    correct = answer
                count = int(tdata[key])
                if answer in rdata:
                    count += rdata[answer] / 100.0 * tot
                pct = round(count / tot * 100.0)

                if answer != "undefined" and answer != "":
                    rdata[answer] = pct
            except:
                print "Bad data for %s data is %s " % (question, key)

    miscdata['correct'] = correct
    miscdata['course'] = course

    getCorrectStats(miscdata, 'mChoice')

    returnDict = dict(answerDict=rdata, misc=miscdata)

    if auth.user and verifyInstructorStatus(course, auth.user.id):  # auth.has_membership('instructor', auth.user.id):
        resultList = getStudentResults(question)
        returnDict['reslist'] = resultList

    return json.dumps([returnDict])


def getpollresults():
    course = request.vars.course
    div_id = request.vars.div_id

    response.headers['content-type'] = 'application/json'

    query = '''select act from useinfo
               where event = 'poll' and div_id = '%s' and course_id = '%s'
               ''' % (div_id, course)
    rows = db.executesql(query)

    result_list = []
    for row in rows:
        val = row[0].split(":")[0]
        result_list.append(int(val))

    # maps option : count
    opt_counts = Counter(result_list)

    # opt_list holds the option numbers from smallest to largest
    # count_list[i] holds the count of responses that chose option i
    opt_list = sorted(opt_counts.keys())
    count_list = []
    for i in opt_list:
        count_list.append(opt_counts[i])

    return json.dumps([len(result_list), opt_list, count_list, div_id])


def gettop10Answers():
    course = request.vars.course
    question = request.vars.div_id
    # select act, count(*) from useinfo where div_id = 'question4_2_1' group by act;
    response.headers['content-type'] = 'application/json'
    rows = []

    query = '''select act, count(*) from useinfo, courses where event = 'fillb' and div_id = '%s' and useinfo.course_id = '%s' and useinfo.course_id = courses.course_name and timestamp > courses.term_start_date  group by act order by count(*) desc limit 10''' % (question, course)
    try:
        rows = db.executesql(query)
        res = [{'answer':row[0][row[0].index(':') + 1:row[0].rindex(':')],
                'count':row[1]} for row in rows ]
    except:
        res = 'error in query'

    miscdata = {'course': course}
    getCorrectStats(miscdata, 'fillb')

    if auth.user and auth.has_membership('instructor', auth.user.id):
        resultList = getStudentResults(question)
        miscdata['reslist'] = resultList

    return json.dumps([res, miscdata])


def getSphinxBuildStatus():
    task_name = request.vars.task_name
    course_url = request.vars.course_url

    row = scheduler.task_status(task_name)
    st = row['status']

    if st == 'COMPLETED':
        status = 'true'
        return dict(status=status, course_url=course_url)
    elif st == 'RUNNING' or st == 'QUEUED' or st == 'ASSIGNED':
        status = 'false'
        return dict(status=status, course_url=course_url)
    else:  # task failed
        status = 'failed'
        tb = db(db.scheduler_run.task_id == row.id).select().first()['traceback']
        return dict(status=status, traceback=tb)

def getassignmentgrade():
    response.headers['content-type'] = 'application/json'
    if not auth.user:
        return json.dumps([dict(message="not logged in")])

    divid = request.vars.div_id

    result = db(
        (db.code.sid == auth.user.username) &
        (db.code.acid == db.problems.acid) &
        (db.problems.assignment == db.assignments.id) &
        (db.assignments.released == True) &
        (db.code.acid == divid)
        ).select(
            db.code.grade,
            db.code.comment,
        ).first()

    ret = {
        'grade':"Not graded yet",
        'comment': "No Comments",
        'avg': 'None',
        'count': 'None',
    }
    if result:
        ret['grade'] = result.grade
        if result.comment:
            ret['comment'] = result.comment

        query = '''select avg(grade), count(grade)
                   from code where acid='%s';''' % (divid)

        rows = db.executesql(query)
        ret['avg'] = rows[0][0]
        ret['count'] = rows[0][1]

    return json.dumps([ret])

# use local timezone for bigbang, not utc, because
# timestamps in the db are generated from local timezone
bigbang = datetime.datetime.fromtimestamp(0)    
def timesincebb(ts):
    if ts:
        return (ts-bigbang).total_seconds()*1000
    else:
        return 0

def getPageSessions():
    sid = request.vars.sid
    # need to add protection so they can only get data for own sid, or instructor can get anyone's
    
    q = '''select timestamp, event, div_id
           from useinfo 
           where sid = '%s'
           order by timestamp
    '''  % (sid)
    rows = db.executesql(q)

    import datetime
    # first process to find starting and ending time of each page session
    sessions = []
    def chapter_url(full_url):
        # return canonical url, without #anchors
        if full_url.rfind('#') > 0:
            full_url = full_url[:url.rfind('#')]
        full_url = full_url.replace('/runestone/static/pip/', '')
        return full_url
    class Session(object):
    
        def __init__(self, url, start, end = None):
            self.url = chapter_url(url)
            self.start = start
            self.end = end

    # make initial sessions
    if len(rows)>0:
        sessions.append(Session(rows[0][2], timesincebb(rows[0][0])))
        
    for i in range(1,len(rows)):
        prev = rows[i-1]
        row = rows[i]
        if (row[0] - prev[0]).total_seconds() > 300: #it's been too long
            sessions[-1].end = sessions[-1].start + 300*1000   # set end time of last sesion; 5 minutes after it started           
            if row[1] == 'page':
                sessions.append(Session(row[2], timesincebb(row[0]))) # add new session, with new page as url
            else:
                sessions.append(Session(sessions[-1].url, timesincebb(row[0]))) # add new session, with old url as last page
        elif row[1] == 'page': # new page but it hasn't been too long
            sessions[-1].end = timesincebb(row[0])   # set end time of last sesion to be this activity's start time           
            sessions.append(Session(row[2], timesincebb(row[0]))) # add new session with current page's url
        else:
            pass    # continuing the page session
            
        
            
    sessions[-1].end = sessions[-1].start + 300*1000   # set end time of last sesion
    
    # then group sessions to make data for swim lanes
    lanes = {}
    for s in sessions:
        if s.url not in lanes:
            lanes[s.url]=[]
        lanes[s.url].append({'starting_time':s.start, 'ending_time':s.end})
        
    return json.dumps([{'label': k, 'times': lanes[k]} for k in lanes])    

def getSessionActivities():
    
    def ts_from_epoch_ms(ms):
        secs = int(ms/1000.0)
        dt = datetime.datetime.fromtimestamp(secs)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # next two lines for testing purposes only
#    request.vars.start = 1388684937000.0
#    request.vars.end = 1488684938000.0
        
    sid = request.vars.sid
    start = ts_from_epoch_ms(float(request.vars.start))
    end = ts_from_epoch_ms(float(request.vars.end))
    print start
    print end
    q = '''select timestamp, event, div_id
           from useinfo 
           where sid = '%s' and timestamp >= '%s' and timestamp <= '%s'
           order by timestamp
    '''  % (sid, start, end)
        

    class Activity(object):
    
        def __init__(self, divid, start, end = None):
            self.divid = divid
            self.start = start
            self.end = end
    #####
    #    -- list of dictionaries, one for each color
    #    -- label for each dictionary
    #    -- label for each item: not sure of format for that yet
    #    -- {'label': start | continue, 
    #        times:[{'hover_text': xxx, 'starting_time': , 'ending_time': }, {}]}
    rows = db.executesql(q)
#    return json.dumps([start, end, q, len(rows)])

    # two types: those that start a new activity and those that continue 
    # go through rows and mark each as either starting or continuing.
    
    starts = []
    continues = []
    
    if len(rows)>0:
        last_activity = Activity(rows[0][2], timesincebb(rows[0][0]))
        starts.append(last_activity)
        
    for i in range(1,len(rows)):
        prev = rows[i-1]
        row = rows[i]
        start = timesincebb(row[0])
        last_activity.end = min(start, last_activity.start + 1000*5*60)  # last activity ends now, or after 5 minutes, whichever comes sooner
        current_act = Activity(row[2], start)
        if current_act.divid == last_activity.divid:
            continues.append(current_act)
        else:
            starts.append(current_act)
        last_activity = current_act

    last_activity.end = last_activity.start + 10*1000
    
    #return json.dumps([start, end, q, len(rows), len(starts), len(continues)])

       
    return json.dumps([{'label': 'start', 'color': 'red', 'times': [{'starting_time':s.start, 'ending_time':s.end, 'hover_text': s.divid} for s in starts]},
                       {'label': 'continue', 'color': 'black', 'times': [{'starting_time':s.start, 'ending_time':s.end, 'hover_text': s.divid} for s in continues]}])    
       
       
def getCodeDiffs():
    print "1"
    sid = request.vars.sid
    ex = request.vars.div_id
    q = '''select timestamp, sid, div_id, code, emessage
           from acerror_log 
           where sid = '%s' and div_id='%s'
           order by timestamp
    '''  % (sid, ex)

    rows = db.executesql(q)
    
    differ = diff_match_patch()
    ts = []
    newcode = []
    diffcode = []
    messages = []
    


    for i in range(1,len(rows)):
        diffs = differ.diff_main(rows[i-1][3],rows[i][3])
        ts.append(str(rows[i][0]))
        newcode.append(rows[i][3])
        diffcode.append(differ.diff_prettyHtml(diffs))
        messages.append(rows[i][4])
    
    import datetime
    bigbang = datetime.datetime.utcfromtimestamp(0)    
    acts = []
    for i in range(0,len(rows)-1):
        row = rows[i]
        next = rows[i+1]
        acts.append({"starting_time": timesincebb(row[0]),
                     "ending_time": min(timesincebb(next[0]), timesincebb(row[0])+10*1000)})
    test = [{'label': "runs", 'color': 'black', 'times': acts}]
#    print test
       
#    test = [{'label': "runs", 'fruit': 'orange', 'times': \
#             [{"starting_time": (row[0]-bigbang).total_seconds()*1000, "ending_time": ((row[0]-bigbang).total_seconds()+5)*1000} for row in rows]
#             }
#            ]
#   
#    test = [
#      {'label': "fruit 1", 'fruit': "orange", 'times': [
#        {"starting_time": 1355759910000, "ending_time": 1355761900000}]},
#      {'label': "fruit 2", 'fruit': "apple", 'times': [
#        {"starting_time": 1355752800000, "ending_time": 1355759900000}, 
#        {"starting_time": 1355767900000, "ending_time": 1355774400000}]},
#      ]
        
    return json.dumps(dict(timestamps=ts,code=newcode,diffs=diffcode,mess=messages, d3data=test))
        
