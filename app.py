from flask import Flask, request, make_response
from flask_restful import Resource, Api
import json
from model import get_features_by_id, select_feature_association, select_feature_matrix, get_db_connection, get_ids_by_feature, opposite, cohort_id_in_use, select_cohort, get_cohort_features, get_cohort_dictionary, service_name, get_cohort_by_id, validate_range, get_id_by_name, add_name_by_id
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from jsonschema import validate, ValidationError
from schema import cohort_schema, feature_association_schema, feature_association2_schema, associations_to_all_features_schema, add_name_by_id_schema
from flasgger import Swagger
import traceback
from format import format_tabular
import csv
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from time import strftime
from structlog import wrap_logger
from structlog.processors import JSONRenderer

with open('terms.txt', 'r') as content_file:
    terms_and_conditions = content_file.read()

logger = logging.getLogger("Rotating Log")
logger.setLevel(logging.INFO)

handler = TimedRotatingFileHandler(os.environ["ICEES_API_LOG_PATH"])

logger.addHandler(handler)
logger = wrap_logger(logger, processors=[JSONRenderer()])

app = Flask(__name__)
limiter = Limiter(
    app,
    key_func=lambda: "client", # get_remote_address,
    default_limits=["10/second"]
)

app.config["SWAGGER"] = {
  "ui_params_text": '''{
    "operationsSorter" : (a,b) => {
        const ordering = [
          "/{version}/{table}/{year}/cohort/{cohort_id}/features", 
          "/{version}/{table}/{year}/cohort/{cohort_id}/feature_association", 
          "/{version}/{table}/{year}/cohort/{cohort_id}/feature_association2", 
          "/{version}/{table}/{year}/cohort/{cohort_id}/associations_to_all_features"
        ]
        const apath = a.get("path")
        const bpath = b.get("path")
        const aorder = ordering.indexOf(apath)
        const border = ordering.indexOf(bpath)
        if(aorder >= 0) {
          if (border >= 0) {
            return aorder - border
          } else {
            return ordering[0].localeCompare(bpath)
          }
        } else if (border >= 0) {
          return apath.localeCompare(ordering[0])
        } else {
          return apath.localeCompare(bpath)
        }
    }
  }'''
}

@app.after_request
def after_request(response):
    timestamp = strftime('%Y-%b-%d %H:%M:%S')
    logger.info(event="request", timestamp=timestamp, remote_addr=request.remote_addr, method=request.method, schema=request.scheme, full_path=request.full_path, data=request.get_json(), response_status=response.status)
    return response

api = Api(app)

template = {
  "info": {
    "title": "ICEES API",
      "description": """ICEES API 
<br>[documentation](https://github.com/NCATS-Tangerine/icees-api/tree/master/docs) 
<br>[source](https://github.com/NCATS-Tangerine/icees-api/tree/master/) 
<br>[ICEES API example queries](https://github.com/NCATS-Tangerine/icees-api/tree/master/#examples) <br>dictionary for versioning of tables<br><table><tr><th>version</th><th>table content</th></tr><tr><td>1.0.0</td><td>cdw, acs, nearest road, and cmaq from 2010</td></tr></table>""",
    "version": "0.0.1"
  },
  "consumes": [
    "application/json"
  ],
  "produces": [
    "application/json",
    "text/tabular"
  ],
  "host": "icees.renci.org",  # overrides localhost:500
  "basePath": "/",  # base bash for blueprint registration
  "schemes": [
    "https"
  ]
}

swag = Swagger(app, template=template)

@api.representation('application/json')
def output_json(data, code, headers=None):
    resp = make_response(json.dumps({"terms and conditions": terms_and_conditions, "return value": data}), code)
    resp.headers.extend(headers or {})
    return resp

@api.representation('text/tabular')
def output_tabular(data, code, headers=None):
    resp = make_response(format_tabular(terms_and_conditions, data), code)
    resp.headers.extend(headers or {})
    return resp

class SERVCohort(Resource):
    def post(self, version, table, year):
        """
        Cohort discovery. Users define a cohort using any number of defined feature variables as input parameters, and the service returns a sample size. If a cohort is already created for this set before, return cohort id and size. Otherwise, generate a new cohort id.
        ---
        parameters:
          - in: body
            name: body
            description: feature variables
            schema: 
              oneOf:
                - import: "definitions/cohort_patient_input.yaml"
                - import: "definitions/cohort_visit_input.yaml"
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
        responses:
          201:
            description: The cohort has been created
            schema:
              oneOf:
                - import: "definitions/cohort_patient_output.yaml"
                - import: "definitions/cohort_visit_output.yaml"
        """
        try:
            conn = get_db_connection(version)
            req_features = request.get_json()
            if req_features is None:
                req_features = {}
            else:
                validate(req_features, cohort_schema(table))

            cohort_id, size = get_ids_by_feature(conn, table, year, req_features)
      
            if size == -1:
                return "Input features invalid or cohort ≤10 patients. Please try again."
            else:
                return {
                    "cohort_id": cohort_id,
                    "size": size
                }
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)

class SERVCohortId(Resource):
    def put(self, version, table, year, cohort_id):
        """
        Cohort discovery. Users define a cohort using any number of defined feature variables as input parameters, and the service returns a sample size. A new cohort is created even if a cohort was previously created using the same input parameters.
        ---
        parameters:
          - in: body
            name: body
            description: feature variables
            schema: 
              oneOf:
                - import: "definitions/cohort_patient_input.yaml"
                - import: "definitions/cohort_visit_input.yaml"
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
          - in: path
            name: cohort_id
            required: false
            description: the cohort id
            type: string
            default: COHORT:22
        responses:
          201:
            description: The cohort has been created
            schema:
              oneOf:
                - import: "definitions/cohort_patient_output.yaml"
                - import: "definitions/cohort_visit_output.yaml"
        """
        try:
            conn = get_db_connection(version)
            req_features = request.get_json()
            if req_features is None:
                req_features = {}
            else:
                validate(req_features, cohort_schema(table))

            cohort_id, size = select_cohort(conn, table, year, req_features, cohort_id)

            if size == -1:
                return "Input features invalid or cohort ≤10 patients. Please try again."
            else:
                return {
                    "cohort_id": cohort_id,
                    "size": size
                }
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)

    def get(self, version, table, year, cohort_id):
        """
        Get definition of a cohort
        ---
        parameters:
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
          - in: path
            name: cohort_id
            required: true
            description: the cohort id
            type: string
            default: COHORT:22
        responses:
          200:
            description: The features of the cohort
            schema:
              oneOf: 
                - import: "definitions/cohort_patient_input.yaml"
                - import: "definitions/cohort_visit_input.yaml"
        """
        try:
            conn = get_db_connection(version)
            cohort_features = get_cohort_by_id(conn, table, year, cohort_id)
            
            if cohort_features is None:
                return "Input cohort_id invalid. Please try again."
            else:
                return cohort_features
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)


def to_qualifiers(feature):
    k, v = list(feature.items())[0]
    return {
        "feature_name": k,
        "feature_qualifiers": [v, opposite(v)]
    }


class SERVFeatureAssociation(Resource):
    def post(self, version, table, year, cohort_id):
        """
        Hypothesis-driven 2 x 2 feature associations: users select a predefined cohort and two feature variables, and the service returns a 2 x 2 feature table with a corresponding Chi Square statistic and P value.
        ---
        parameters:
          - in: body
            name: body
            description: two feature variables
            schema: 
              oneOf:
                - import: "definitions/feature_association_patient_input.yaml"
                - import: "definitions/feature_association_visit_input.yaml"
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
          - in: path
            name: cohort_id
            required: true
            description: the cohort id
            type: string
            default: COHORT:22
        responses:
          200:
            description: The feature association
            schema:
              oneOf: 
                - import: "definitions/feature_association_patient_output.yaml"
                - import: "definitions/feature_association_visit_output.yaml"
        """
        try:
            obj = request.get_json()
            validate(obj, feature_association_schema(table))
            feature_a = to_qualifiers(obj["feature_a"])
            feature_b = to_qualifiers(obj["feature_b"])

            conn = get_db_connection(version)
            cohort_features = get_features_by_id(conn, table, year, cohort_id)

            if cohort_features is None:
                return "Input cohort_id invalid. Please try again."
            else:
                return select_feature_matrix(conn, table, year, cohort_features, feature_a, feature_b)
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)

def to_qualifiers2(feature):
    k, v = list(feature.items())[0]
    return {
        "feature_name": k,
        "feature_qualifiers": v
    }


class SERVFeatureAssociation2(Resource):
    def post(self, version, table, year, cohort_id):
        """
        Hypothesis-driven N x N feature associations: users select a predefined cohort, two feature variables, and bins, which can be combined, and the service returns a N x N feature table with a corresponding Chi Square statistic and P value.
        ---
        parameters:
          - in: body
            name: body
            description: two feature variables
            schema: 
              oneOf:
                - import: "definitions/feature_association2_patient_input.yaml"
                - import: "definitions/feature_association2_visit_input.yaml"
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010
            type: integer
            default: 2010
          - in: path
            name: cohort_id
            required: true
            description: the cohort id
            type: string
            default: COHORT:22
        responses:
          200:
            description: The feature association
            schema:
              oneOf: 
                - import: "definitions/feature_association2_patient_output.yaml"
                - import: "definitions/feature_association2_visit_output.yaml"
        """
        try:
            obj = request.get_json()
            validate(obj, feature_association2_schema(table))
            feature_a = to_qualifiers2(obj["feature_a"])
            feature_b = to_qualifiers2(obj["feature_b"])
            to_validate_range = ("check_coverage_is_full" in obj) and obj["check_coverage_is_full"]
            if to_validate_range:
                validate_range(table, feature_a)
                validate_range(table, feature_b)

            conn = get_db_connection(version)
            cohort_features = get_features_by_id(conn, table, year, cohort_id)

            if cohort_features is None:
                return "Input cohort_id invalid. Please try again."
            else:
                return select_feature_matrix(conn, table, year, cohort_features, feature_a, feature_b)
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)


class SERVAssociationsToAllFeatures(Resource):
    def post(self, version, table, year, cohort_id):
        """
        Exploratory 1 X N feature associations: users select a predefined cohort and a feature variable of interest, and the service returns a 1 x N feature table with corrected Chi Square statistics and associated P values.
        ---
        parameters:
          - in: body
            name: body
            description: a feature variable and minimum p value
            schema: 
              oneOf:
                - import: "definitions/associations_to_all_features_patient_input.yaml"
                - import: "definitions/associations_to_all_features_visit_input.yaml"
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
          - in: path
            name: cohort_id
            required: true
            description: the cohort id
            type: string
            default: COHORT:22
        responses:
          200:
            description: Associations to all features
            schema:
              oneOf:
                - import: "definitions/associations_to_all_features_patient_output.yaml"
                - import: "definitions/associations_to_all_features_visit_output.yaml"
        """
        try:
            obj = request.get_json()
            validate(obj, associations_to_all_features_schema(table))
            feature = to_qualifiers(obj["feature"])
            maximum_p_value = obj["maximum_p_value"]
            conn = get_db_connection(version)
            cohort_features = get_features_by_id(conn, table, year, cohort_id)
            if cohort_features is None:
                return "Input cohort_id invalid. Please try again."
            else:
                return select_feature_association(conn, table, year, cohort_features, feature, maximum_p_value)
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)


class SERVFeatures(Resource):
    def get(self, version, table, year, cohort_id):
        """
        Feature-rich cohort discovery: users select a predefined cohort as the input parameter, and the service returns a profile of that cohort in terms of all feature variables.
        ---
        parameters:
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
          - in: path
            name: cohort_id
            required: true
            description: the cohort id
            type: string
            default: COHORT:22
        responses:
          200:
            description: features
            schema:
              oneOf:
                - import: "definitions/features_patient_output.yaml"
                - import: "definitions/features_visit_output.yaml"
        """
        try:
            conn = get_db_connection(version)
            cohort_features = get_features_by_id(conn, table, year, cohort_id)
            if cohort_features is None:
                return "Input cohort_id invalid. Please try again."
            else:
                return get_cohort_features(conn, table, year, cohort_features)
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)


class SERVCohortDictionary(Resource):
    def get(self, version, table, year):
        """
        Get cohort dictionary
        ---
        parameters:
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: year
            required: true
            description: the year 2010|2011
            type: integer
            default: 2010
        responses:
          200:
            description: cohort dictionray
            schema:
              oneOf:
                - import: "definitions/cohort_dictionary_patient_output.yaml"
                - import: "definitions/cohort_dictionary_visit_output.yaml"
        """
        try:
            conn = get_db_connection(version)
            return get_cohort_dictionary(conn, table, year)
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)

class SERVIdentifiers(Resource):
    def get(self, version, table, feature):
        """
        Feature identifiers.
        ---
        parameters:
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: feature
            required: true
            description: feature
            type: string
            default: 
        responses:
          200:
            description: feature identifiers
            schema:
              import: "definitions/identifiers_output.yaml"
        """
        try:
            pat_dict = {}
            visit_dict = {}
            version_map = {
                "1.0.0" : "ICEES_Identifiers_12.04.18.csv"
            }
            if version in version_map:
                with open(version_map[version], newline="") as f:
                    csvreader = csv.reader(f, delimiter=",", quotechar="\"")
                    next(csvreader)
                    for row in csvreader:
                        row2 = filter(lambda x : x != "", map(lambda x : x.strip(), row))
                        pat = next(row2)
                        visit = next(row2)
                        ids = list(row2)
                        if pat != "N/A":
                            pat_dict[pat] = ids
                            if visit != "N/A":
                                visit_dict[visit] = ids
            else:
                return "Cannot find version " + version
            if table == "patient":
                identifier_dict = pat_dict
            elif table == "visit":
                identifier_dict = visit_dict
            else:
                return "Cannot find table " + table

            if feature in identifier_dict:
                return {
                    "identifiers": identifier_dict[feature]
                }
            else:
                return "Cannot find identifiers for feature " + feature
        except Exception as e:
            traceback.print_exc()
            return str(e)


class SERVName(Resource):
    def get(self, version, table, name):
        """
        Return cohort id associated with name.
        ---
        parameters:
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: name
            required: true
            description: name
            type: string
        responses:
          200:
            description: cohort id and name
            schema:
              import: "definitions/name_output.yaml"
        """
        try:
            conn = get_db_connection(version)
            return get_id_by_name(conn, table, name)
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)


    def post(self, version, table, name):
        """
        Associate name with cohort id.
        ---
        parameters:
          - in: body
            name: body
            description: cohort id
            schema: 
              import: "definitions/add_name_by_id_input.yaml"
          - in: path
            name: version
            required: true
            description: version of data 1.0.0
            type: string
            default: 1.0.0
          - in: path
            name: table
            required: true
            description: the table patient|visit
            type: string
            default: patient
          - in: path
            name: name
            required: true
            description: name
            type: string
        responses:
          200:
            description: cohort id and name
            schema:
              import: "definitions/name_output.yaml"
        """
        try:
            obj = request.get_json()
            validate(obj, add_name_by_id_schema())
            conn = get_db_connection(version)
            return add_name_by_id(conn, table, name, obj["cohort_id"])
        except ValidationError as e:
            traceback.print_exc()
            return e.message
        except Exception as e:
            traceback.print_exc()
            return str(e)


api.add_resource(SERVCohort, '/<string:version>/<string:table>/<int:year>/cohort')
api.add_resource(SERVCohortId, '/<string:version>/<string:table>/<int:year>/cohort/<string:cohort_id>')
api.add_resource(SERVFeatures, '/<string:version>/<string:table>/<int:year>/cohort/<string:cohort_id>/features')
api.add_resource(SERVCohortDictionary, '/<string:version>/<string:table>/<int:year>/cohort/dictionary')
api.add_resource(SERVFeatureAssociation, '/<string:version>/<string:table>/<int:year>/cohort/<string:cohort_id>/feature_association')
api.add_resource(SERVFeatureAssociation2, '/<string:version>/<string:table>/<int:year>/cohort/<string:cohort_id>/feature_association2')
api.add_resource(SERVAssociationsToAllFeatures, '/<string:version>/<string:table>/<int:year>/cohort/<string:cohort_id>/associations_to_all_features')
api.add_resource(SERVIdentifiers, "/<string:version>/<string:table>/<string:feature>/identifiers")
api.add_resource(SERVName, "/<string:version>/<string:table>/name/<string:name>")

if __name__ == '__main__':

    app.run()
