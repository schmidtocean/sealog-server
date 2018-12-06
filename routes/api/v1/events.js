'use strict';

const Joi = require('joi');
const converter = require('json-2-csv');
const extend = require('jquery-extend');

const json2csvOptions = {
  checkSchemaDifferences: false,
  emptyFieldValue: ''
};

const THRESHOLD = 120; //seconds

const {
  eventsTable,
  usersTable,
  eventAuxDataTable,
  loweringsTable,
  cruisesTable
} = require('../../../config/db_constants');


function flattenJSON(json) {
  // console.log("Pre-Export:", this.props.event_export.events)
  let exportData = json.map((event) => {
    let copiedEvent = extend(true, {}, event);

    copiedEvent.event_options.map((data) => {
      let elementName = `event_option_${data.event_option_name}`;
      // console.log(elementName, data.event_option_value);
      copiedEvent[elementName] = data.event_option_value;
    });

    delete copiedEvent.event_options;

    copiedEvent.ts = copiedEvent.ts.toISOString();
    copiedEvent.id = copiedEvent.id.toString();
    return copiedEvent;
  });

  return exportData;
}

exports.register = function (server, options, next) {

  const db = server.mongo.db;
  const ObjectID = server.mongo.ObjectID;

  const _renameAndClearFields = (doc) => {

    //rename id
    doc.id = doc._id;
    delete doc._id;

    return doc;
  };

  server.route({
    method: 'GET',
    path: '/events/bycruise/{id}',
    handler: function (request, reply) {

      db.collection(cruisesTable).findOne({ _id: ObjectID(request.params.id) }).then((cruise) => {

        if(cruise.cruise_hidden && !request.auth.credentials.scope.includes("admin")) {
          return reply({ "statusCode": 401, "error": "not authorized", "message": "User not authorized to retrieve hidden cruises"}).code(401);
        }

        let query = {};
        let startTS = new Date(cruise.start_ts);
        let stopTS = new Date(cruise.stop_ts);

        // console.log(request.query);

        //Data source filtering
        if (request.query.datasource) {

          let datasource_query = {};

          if(Array.isArray(request.query.datasource)) {
            datasource_query.data_source  = { $in: request.query.datasource };
          } else {
            datasource_query.data_source  = request.query.datasource;
          }

          db.collection(eventAuxDataTable).find(datasource_query, {_id: 0, event_id: 1}).toArray().then((collection) => {

            let eventIDs = collection.map(x => x.event_id);

            // console.log("collection:", eventIDs);

            query._id = { $in: eventIDs};


            if(request.query.author) {
              if(Array.isArray(request.query.author)) {
                query.event_author  = { $in: request.query.author };
              } else {
                query.event_author  = request.query.author;
              }
            }

            if(request.query.value) {
              if(Array.isArray(request.query.value)) {

                let inList = [];
                let ninList = [];

                for( let value of request.query.value ) {
                  if(value.startsWith("!")) {
                    ninList.push(value.substr(1));
                  } else {
                    inList.push(value);
                  }
                }
                
                if( inList.length > 0 && ninList.length > 0) {
                  query.event_value  = { $in: inList, $nin: ninList };
                } else if (inList.length > 0) {
                  query.event_value  = { $in: inList };
                } else {
                  query.event_value  = { $nin: ninList };
                }

              } else {
                if(request.query.value.startsWith("!")) {
                  query.event_value  = { $ne: request.query.value.substr(1) };
                } else {
                  query.event_value  = request.query.value;
                }
              }
            }

            if(request.query.freetext) {

              query.event_free_text = { $regex: `${request.query.freetext}`};
            }

            //Time filtering
            if (request.query.startTS) {
              let tempStartTS = new Date(request.query.startTS);
              // console.log("tempStartTS:", tempStartTS);
              startTS = (tempStartTS >= startTS && tempStartTS <= stopTS)? tempStartTS : startTS;
              // console.log("startTS:", startTS);
            }

            if (request.query.stopTS) {
              let tempStopTS = new Date(request.query.stopTS);
              // console.log("tempStopTS:", tempStopTS);
              stopTS = (tempStopTS >= startTS && tempStopTS <= stopTS)? tempStopTS : stopTS;
              // console.log("stopTS:", stopTS);
            }

            query.ts = {"$gte": startTS , "$lte": stopTS };

            let limit = (request.query.limit)? request.query.limit : 0;
            let offset = (request.query.offset)? request.query.offset : 0;

            // console.log("query:", query);

            db.collection(eventsTable).find(query).sort( { ts: 1 } ).skip(offset).limit(limit).toArray().then((results) => {
              // console.log("results:", results);

              if (results.length > 0) {
                results.forEach(_renameAndClearFields);
                return reply(results).code(200);
              } else {
                return reply({ "statusCode": 404, 'message': 'No records found'}).code(404);
              }
            }).catch((err) => {
              console.log("ERROR:", err);
              return reply().code(503);
            });
          }).catch((err) => {
            console.log("ERROR:", err);
            return reply().code(503);
          });
        } else {

          if(request.query.author) {
            if(Array.isArray(request.query.author)) {
              query.event_author  = { $in: request.query.author };
            } else {
              query.event_author  = request.query.author;
            }
          }

          if(request.query.value) {
            if(Array.isArray(request.query.value)) {

              let inList = [];
              let ninList = [];

              for( let value of request.query.value ) {
                if(value.startsWith("!")) {
                  ninList.push(value.substr(1));
                } else {
                  inList.push(value);
                }
              }

              if( inList.length > 0 && ninList.length > 0) {
                query.event_value  = { $in: inList, $nin: ninList };
              } else if (inList.length > 0) {
                query.event_value  = { $in: inList };
              } else {
                query.event_value  = { $nin: ninList };
              }

            } else {
              if(request.query.value.startsWith("!")) {
                query.event_value  = { $ne: request.query.value.substr(1) };
              } else {
                query.event_value  = request.query.value;
              }
            }
          }

          if(request.query.freetext) {

            query.event_free_text = { $regex: `${request.query.freetext}`};
          }

          //Time filtering
          if (request.query.startTS) {
            let tempStartTS = new Date(request.query.startTS);
            // console.log("tempStartTS:", tempStartTS);
            startTS = (tempStartTS >= startTS && tempStartTS <= stopTS)? tempStartTS : startTS;
            // console.log("startTS:", startTS);
          }

          if (request.query.stopTS) {
            let tempStopTS = new Date(request.query.stopTS);
            stopTS = (tempStopTS >= startTS && tempStopTS <= stopTS)? tempStopTS : stopTS;
          }

          query.ts = {"$gte": startTS , "$lte": stopTS };

          let limit = (request.query.limit)? request.query.limit : 0;
          let offset = (request.query.offset)? request.query.offset : 0;

          // console.log("query:", query);

          db.collection(eventsTable).find(query).sort( { ts: 1  } ).skip(offset).limit(limit).toArray().then((results) => {
            // console.log("results:", results);

            if (results.length > 0) {

              results.forEach(_renameAndClearFields);

              if(request.query.format && request.query.format == "csv") {
                converter.json2csv(flattenJSON(results), (err, csv) => {
                  if(err) {
                    throw err;
                  }
                  return reply(csv).code(200);
                }, json2csvOptions);
              } else {
                return reply(results).code(200);
              }
            } else {
              return reply({ "statusCode": 404, 'message': 'No records found'}).code(404);
            }
          }).catch((err) => {
            console.log("ERROR:", err);
            return reply().code(503);
          });
        }
      }).catch((err) => {
        console.log(err);
        return reply({ "statusCode": 404, 'message': 'No cruise record found for that id'}).code(404);
      });
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin', 'cruise_manager', 'event_manager', 'event_logger', 'event_watcher']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        params: Joi.object({
          id: Joi.string().length(24).required()
        }),
        query: Joi.object({
          format: Joi.string().optional(),
          offset: Joi.number().integer().min(0).optional(),
          limit: Joi.number().integer().min(1).optional(),
          author: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          startTS: Joi.date().iso(),
          stopTS: Joi.date().iso(),
          datasource: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          value: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          freetext: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
        }).optional(),
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          200: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.object({
              id: Joi.object(),
              event_author: Joi.string(),
              ts: Joi.date().iso(),
              event_value: Joi.string(),
              event_options: Joi.array().items(Joi.object({
                event_option_name: Joi.string(),
                event_option_value: Joi.string().allow('')
              })),
              event_free_text: Joi.string().allow(''),
            }))
          ),
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          404: Joi.object({
            statusCode: Joi.number().integer(),
            message: Joi.string()
          })
        }
      },
      description: 'Return the events based on query parameters',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong>, <strong>event_logger</strong> or <strong>event_watcher</strong></p>',
      tags: ['events','auth', 'api'],
    }
  });

  server.route({
    method: 'GET',
    path: '/events/bylowering/{id}',
    handler: function (request, reply) {

      db.collection(loweringsTable).findOne({ _id: ObjectID(request.params.id) }).then((lowering) => {

        if(lowering.lowering_hidden && !request.auth.credentials.scope.includes("admin")) {
          return reply({ "statusCode": 401, "error": "not authorized", "message": "User not authorized to retrieve hidden lowerings"}).code(401);
        }

        let query = {};
        let startTS = new Date(lowering.start_ts);
        let stopTS = new Date(lowering.stop_ts);

        // console.log(request.query);

        //Data source filtering
        if (request.query.datasource) {

          let datasource_query = {};

          if(Array.isArray(request.query.datasource)) {
            datasource_query.data_source  = { $in: request.query.datasource };
          } else {
            datasource_query.data_source  = request.query.datasource;
          }

          db.collection(eventAuxDataTable).find(datasource_query, {_id: 0, event_id: 1}).toArray().then((collection) => {

            let eventIDs = collection.map(x => x.event_id);

            // console.log("collection:", eventIDs);

            query._id = { $in: eventIDs};


            if(request.query.author) {
              if(Array.isArray(request.query.author)) {
                query.event_author  = { $in: request.query.author };
              } else {
                query.event_author  = request.query.author;
              }
            }

            if(request.query.value) {
              if(Array.isArray(request.query.value)) {

                let inList = [];
                let ninList = [];

                for( let value of request.query.value ) {
                  if(value.startsWith("!")) {
                    ninList.push(value.substr(1));
                  } else {
                    inList.push(value);
                  }
                }
                
                if( inList.length > 0 && ninList.length > 0) {
                  query.event_value  = { $in: inList, $nin: ninList };
                } else if (inList.length > 0) {
                  query.event_value  = { $in: inList };
                } else {
                  query.event_value  = { $nin: ninList };
                }

              } else {
                if(request.query.value.startsWith("!")) {
                  query.event_value  = { $ne: request.query.value.substr(1) };
                } else {
                  query.event_value  = request.query.value;
                }
              }
            }

            if(request.query.freetext) {

              query.event_free_text = { $regex: `${request.query.freetext}`};
            }

            //Time filtering
            if (request.query.startTS) {
              let tempStartTS = new Date(request.query.startTS);
              // console.log("tempStartTS:", tempStartTS);
              startTS = (tempStartTS >= startTS && tempStartTS <= stopTS)? tempStartTS : startTS;
              // console.log("startTS:", startTS);
            }

            if (request.query.stopTS) {
              let tempStopTS = new Date(request.query.stopTS);
              // console.log("tempStopTS:", tempStopTS);
              stopTS = (tempStopTS >= startTS && tempStopTS <= stopTS)? tempStopTS : stopTS;
              // console.log("stopTS:", stopTS);
            }

            query.ts = {"$gte": startTS , "$lte": stopTS };

            let limit = (request.query.limit)? request.query.limit : 0;
            let offset = (request.query.offset)? request.query.offset : 0;

            // console.log("query:", query);

            db.collection(eventsTable).find(query).sort( { ts: 1 } ).skip(offset).limit(limit).toArray().then((results) => {
              // console.log("results:", results);

              if (results.length > 0) {
                results.forEach(_renameAndClearFields);
                return reply(results).code(200);
              } else {
                return reply({ "statusCode": 404, 'message': 'No records found'}).code(404);
              }
            }).catch((err) => {
              console.log("ERROR:", err);
              return reply().code(503);
            });
          }).catch((err) => {
            console.log("ERROR:", err);
            return reply().code(503);
          });
        } else {

          if(request.query.author) {
            if(Array.isArray(request.query.author)) {
              query.event_author  = { $in: request.query.author };
            } else {
              query.event_author  = request.query.author;
            }
          }

          if(request.query.value) {
            if(Array.isArray(request.query.value)) {

              let inList = [];
              let ninList = [];

              for( let value of request.query.value ) {
                if(value.startsWith("!")) {
                  ninList.push(value.substr(1));
                } else {
                  inList.push(value);
                }
              }

              if( inList.length > 0 && ninList.length > 0) {
                query.event_value  = { $in: inList, $nin: ninList };
              } else if (inList.length > 0) {
                query.event_value  = { $in: inList };
              } else {
                query.event_value  = { $nin: ninList };
              }

            } else {
              if(request.query.value.startsWith("!")) {
                query.event_value  = { $ne: request.query.value.substr(1) };
              } else {
                query.event_value  = request.query.value;
              }
            }
          }

          if(request.query.freetext) {

            query.event_free_text = { $regex: `${request.query.freetext}`};
          }

          //Time filtering
          if (request.query.startTS) {
            let tempStartTS = new Date(request.query.startTS);
            // console.log("tempStartTS:", tempStartTS);
            startTS = (tempStartTS >= startTS && tempStartTS <= stopTS)? tempStartTS : startTS;
            // console.log("startTS:", startTS);
          }

          if (request.query.stopTS) {
            let tempStopTS = new Date(request.query.stopTS);
            stopTS = (tempStopTS >= startTS && tempStopTS <= stopTS)? tempStopTS : stopTS;
          }

          query.ts = {"$gte": startTS , "$lte": stopTS };

          let limit = (request.query.limit)? request.query.limit : 0;
          let offset = (request.query.offset)? request.query.offset : 0;

          // console.log("query:", query);

          db.collection(eventsTable).find(query).sort( { ts: 1  } ).skip(offset).limit(limit).toArray().then((results) => {
            // console.log("results:", results);

            if (results.length > 0) {

              results.forEach(_renameAndClearFields);

              if(request.query.format && request.query.format == "csv") {
                converter.json2csv(flattenJSON(results), (err, csv) => {
                  if(err) {
                    throw err;
                  }
                  return reply(csv).code(200);
                }, json2csvOptions);
              } else {
                return reply(results).code(200);
              }
            } else {
              return reply({ "statusCode": 404, 'message': 'No records found'}).code(404);
            }
          }).catch((err) => {
            console.log("ERROR:", err);
            return reply().code(503);
          });
        }
      }).catch((err) => {
        console.log(err);
        return reply({ "statusCode": 404, 'message': 'No lowering record found for that id'}).code(404);
      });
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin', 'cruise_manager', 'event_manager', 'event_logger', 'event_watcher']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        params: Joi.object({
          id: Joi.string().length(24).required()
        }),
        query: Joi.object({
          format: Joi.string().optional(),
          offset: Joi.number().integer().min(0).optional(),
          limit: Joi.number().integer().min(1).optional(),
          author: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          startTS: Joi.date().iso(),
          stopTS: Joi.date().iso(),
          datasource: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          value: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          freetext: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
        }).optional(),
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          200: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.object({
              id: Joi.object(),
              event_author: Joi.string(),
              ts: Joi.date().iso(),
              event_value: Joi.string(),
              event_options: Joi.array().items(Joi.object({
                event_option_name: Joi.string(),
                event_option_value: Joi.string().allow('')
              })),
              event_free_text: Joi.string().allow(''),
            }))
          ),
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          404: Joi.object({
            statusCode: Joi.number().integer(),
            message: Joi.string()
          })
        }
      },
      description: 'Return the events based on query parameters',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong>, <strong>event_logger</strong> or <strong>event_watcher</strong></p>',
      tags: ['events','auth', 'api'],
    }
  });

  server.route({
    method: 'GET',
    path: '/events',
    handler: function (request, reply) {

      let query = {};

      // console.log(request.query);

      //Data source filtering
      if (request.query.datasource) {

        let datasource_query = {};

        if(Array.isArray(request.query.datasource)) {
          datasource_query.data_source  = { $in: request.query.datasource };
        } else {
          datasource_query.data_source  = request.query.datasource;
        }

        db.collection(eventAuxDataTable).find(datasource_query, {_id: 0, event_id: 1}).toArray().then((collection) => {

          let eventIDs = collection.map(x => x.event_id);

          // console.log("collection:", eventIDs);

          query._id = { $in: eventIDs};


          if(request.query.author) {
            if(Array.isArray(request.query.author)) {
              query.event_author  = { $in: request.query.author };
            } else {
              query.event_author  = request.query.author;
            }
          }

          if(request.query.value) {
            if(Array.isArray(request.query.value)) {

              let inList = [];
              let ninList = [];

              for( let value of request.query.value ) {
                if(value.startsWith("!")) {
                  ninList.push(value.substr(1));
                } else {
                  inList.push(value);
                }
              }
              
              if( inList.length > 0 && ninList.length > 0) {
                query.event_value  = { $in: inList, $nin: ninList };
              } else if (inList.length > 0) {
                query.event_value  = { $in: inList };
              } else {
                query.event_value  = { $nin: ninList };
              }

            } else {
              if(request.query.value.startsWith("!")) {
                query.event_value  = { $ne: request.query.value.substr(1) };
              } else {
                query.event_value  = request.query.value;
              }
            }
          }

          if(request.query.freetext) {

            query.event_free_text = { $regex: `${request.query.freetext}`};
          }

          //Time filtering
          if ((request.query.startTS) || (request.query.stopTS)) {
            let startTS = new Date("1970-01-01T00:00:00.000Z");
            let stopTS = new Date();

            if (request.query.startTS) {
              startTS = new Date(request.query.startTS);
            }

            if (request.query.stopTS) {
              stopTS = new Date(request.query.stopTS);
            }

            query.ts = {"$gte": startTS , "$lte": stopTS };
          }

          let limit = (request.query.limit)? request.query.limit : 0;
          let offset = (request.query.offset)? request.query.offset : 0;
          let sort = (request.query.sort === "newest")? { ts: -1 } : { ts: 1 };

          // console.log("query:", query);

          db.collection(eventsTable).find(query).sort(sort).skip(offset).limit(limit).toArray().then((results) => {
            // console.log("results:", results);

            if (results.length > 0) {
              results.forEach(_renameAndClearFields);
              return reply(results).code(200);
            } else {
              return reply({ "statusCode": 404, 'message': 'No records found'}).code(404);
            }
          }).catch((err) => {
            console.log("ERROR:", err);
            return reply().code(503);
          });
        }).catch((err) => {
          console.log("ERROR:", err);
          return reply().code(503);
        });
      } else {

        if(request.query.author) {
          if(Array.isArray(request.query.author)) {
            query.event_author  = { $in: request.query.author };
          } else {
            query.event_author  = request.query.author;
          }
        }

        if(request.query.value) {
          if(Array.isArray(request.query.value)) {

            let inList = [];
            let ninList = [];

            for( let value of request.query.value ) {
              if(value.startsWith("!")) {
                ninList.push(value.substr(1));
              } else {
                inList.push(value);
              }
            }

            if( inList.length > 0 && ninList.length > 0) {
              query.event_value  = { $in: inList, $nin: ninList };
            } else if (inList.length > 0) {
              query.event_value  = { $in: inList };
            } else {
              query.event_value  = { $nin: ninList };
            }

          } else {
            if(request.query.value.startsWith("!")) {
              query.event_value  = { $ne: request.query.value.substr(1) };
            } else {
              query.event_value  = request.query.value;
            }
          }
        }

        if(request.query.freetext) {

          query.event_free_text = { $regex: `${request.query.freetext}`};
        }

        //Time filtering
        if ((request.query.startTS) || (request.query.stopTS)) {
          let startTS = new Date("1970-01-01T00:00:00.000Z");
          let stopTS = new Date();

          if (request.query.startTS) {
            startTS = new Date(request.query.startTS);
          }

          if (request.query.stopTS) {
            stopTS = new Date(request.query.stopTS);
          }

          query.ts = {"$gte": startTS , "$lte": stopTS };
        }

        let limit = (request.query.limit)? request.query.limit : 0;
        let offset = (request.query.offset)? request.query.offset : 0;
        let sort = (request.query.sort === "newest")? { ts: -1 } : { ts: 1 };

        // console.log("query:", query);

        db.collection(eventsTable).find(query).sort(sort).skip(offset).limit(limit).toArray().then((results) => {
          // console.log("results:", results);

          if (results.length > 0) {

            results.forEach(_renameAndClearFields);

            if(request.query.format && request.query.format == "csv") {
              converter.json2csv(flattenJSON(results), (err, csv) => {
                if(err) {
                  throw err;
                }
                return reply(csv).code(200);
              }, json2csvOptions);
            } else {
              return reply(results).code(200);
            }
          } else {
            return reply({ "statusCode": 404, 'message': 'No records found'}).code(404);
          }
        }).catch((err) => {
          console.log("ERROR:", err);
          return reply().code(503);
        });
      }
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin', 'cruise_manager', 'event_manager', 'event_logger', 'event_watcher']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        query: Joi.object({
          format: Joi.string().optional(),
          offset: Joi.number().integer().min(0).optional(),
          limit: Joi.number().integer().min(1).optional(),
          sort: Joi.string().optional(),
          author: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          startTS: Joi.date().iso(),
          stopTS: Joi.date().iso(),
          datasource: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          value: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
          freetext: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.string()).optional()
          ),
        }).optional(),
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          200: Joi.alternatives().try(
            Joi.string(),
            Joi.array().items(Joi.object({
              id: Joi.object(),
              event_author: Joi.string(),
              ts: Joi.date().iso(),
              event_value: Joi.string(),
              event_options: Joi.array().items(Joi.object({
                event_option_name: Joi.string(),
                event_option_value: Joi.string().allow('')
              })),
              event_free_text: Joi.string().allow(''),
            }))
          ),
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          })
        }
      },
      description: 'Return the events based on query parameters',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong>, <strong>event_logger</strong> or <strong>event_watcher</strong></p>',
      tags: ['events','auth', 'api'],
    }
  });

  server.route({
    method: 'GET',
    path: '/events/{id}',
    handler: function (request, reply) {

      let query = { _id: ObjectID(request.params.id) };

      db.collection(eventsTable).findOne(query).then((result) => {
        if (!result) {
          return reply({ "statusCode": 404, 'message': 'No record found for id: ' + request.params.id }).code(404);
        }

        result = _renameAndClearFields(result);
        return reply(result).code(200);
      }).catch((err) => {
        console.log("ERROR:", err);
        return reply().code(503);
      });
    },
    config: {
      auth:{
        strategy: 'jwt',
        scope: ['admin', 'event_manager', 'event_logger', 'event_watcher']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        params: Joi.object({
          id: Joi.string().length(24).required()
        }),
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          200: Joi.object({
            id: Joi.object(),
            event_author: Joi.string(),
            ts: Joi.date().iso(),
            event_value: Joi.string(),
            event_options: Joi.array().items(Joi.object({
              event_option_name: Joi.string(),
              event_option_value: Joi.string().allow('')
            })),
            event_free_text: Joi.string().allow(''),
          }),
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          404: Joi.object({
            statusCode: Joi.number().integer(),
            message: Joi.string()
          })

        }
      },
      description: 'Return the events based on event id',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong>, <strong>event_logger</strong> or <strong>event_watcher</strong></p>',
      tags: ['events','auth','api'],
    }
  });

  server.route({
    method: 'POST',
    path: '/events',
    handler: function (request, reply) {

      let event = request.payload;

      if(request.payload.id) {
        try {
          event._id = new ObjectID(request.payload.id);
          delete event.id;
        } catch(err) {
          console.log("invalid ObjectID");
          return reply({statusCode: 400, error: "Invalid argument", message: "id must be a single String of 12 bytes or a string of 24 hex characters"}).code(400);
        }
      }

      if(!event.ts) {
        event.ts = new Date();
      }

      if(!event.event_options) {
        event.event_options = [];
      }

      if(!event.event_free_text) {
        event.event_free_text = "";
      }

      if(!event.event_author) {
        db.collection(usersTable).findOne({_id: new ObjectID(request.auth.credentials.id)}, (err, result) => {

          if(err) {
            console.log("ERROR:", err);
            return reply().code(503);
          }

          if (!result) {
            return reply({ "statusCode": 404, 'message': 'No user found for id: ' + request.params.id }).code(404);
          }

          event.event_author = result.username;

          db.collection(eventsTable).insertOne(event, (err, result) => {

            if (err) {
              console.log("ERROR:", err);
              return reply().code(503);
            }

            if (!result) {
              return reply({ "statusCode": 400, 'message': 'Bad request'}).code(400);
            }

            let diff =(new Date().getTime() - event.ts.getTime()) / 1000;
            console.log(diff);
            if(Math.abs(Math.round(diff)) < THRESHOLD) {
              event = _renameAndClearFields(event);
              server.methods.publishNewEvent(event);
            }

            return reply({ n: result.result.n, ok: result.result.ok, insertedCount: result.insertedCount, insertedId: result.insertedId }).code(201);
          });
        });
      } else {

        if(!event.id) {
          db.collection(eventsTable).insertOne(event, (err, result) => {

            if(err) {
              if(err.code === 11000) {
                return reply({statusCode:400, error: "duplicate", message: "duplicate ID"}).code(400);
              } else {
                return reply().code(503);
              }
            }

            if (!result) {
              return reply({ "statusCode": 400, 'message': 'Bad request'}).code(400);
            }

            let diff =(new Date().getTime() - event.ts.getTime()) / 1000;
            console.log(diff);
            if(Math.abs(Math.round(diff)) < THRESHOLD) {
              event = _renameAndClearFields(event);
              server.methods.publishNewEvent(event);
            }

            return reply({ n: result.result.n, ok: result.result.ok, insertedCount: result.insertedCount, insertedId: result.insertedId }).code(201);
          });
        } else {
          db.collection(eventsTable).findOne({_id: new ObjectID(event.id)}, (err, result) => {

            if (err) {
              console.log("ERROR:", err);
              return reply().code(503);
            }

            console.log(event);
            if (!result) {
              db.collection(eventsTable).insertOne(event, (err, result) => {

                if (err) {
                  console.log("ERROR:", err);
                  return reply().code(503);
                }

                if (!result) {
                  return reply({ "statusCode": 400, 'message': 'Bad request'}).code(400);
                }

                event = _renameAndClearFields(event);
                server.methods.publishNewEvent(event);
                return reply({ n: result.result.n, ok: result.result.ok, insertedCount: result.insertedCount, insertedId: result.insertedId }).code(201);
              });
            }

            return reply({ n: result.result.n, ok: result.result.ok, insertedCount: 0, insertedId: 0 }).code(201);
          });
        }
      }
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin', 'event_manager', 'event_logger']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        payload: {
          id: Joi.string().length(24).optional(),
          event_author: Joi.string().min(1).max(100).optional(),
          ts: Joi.date().iso().optional(),
          event_value: Joi.string().min(1).max(100).required(),
          event_options: Joi.array().items(Joi.object({
            event_option_name:Joi.string().required(),
            event_option_value:Joi.string().allow('').required()
          })).optional(),
          event_free_text: Joi.string().allow('').optional()
        },
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          201: Joi.object({
            n: Joi.number().integer(),
            ok: Joi.number().integer(),
            insertedCount: Joi.number().integer(),
            insertedId: Joi.object()
          }),
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          })
        }
      },

      description: 'Create a new event',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong> or <strong>event_logger</strong></p>',
      tags: ['events','auth','api'],
    }
  });

  server.route({
    method: 'PATCH',
    path: '/events/{id}',
    handler: function (request, reply) {

      let query = { _id: new ObjectID(request.params.id) };

      db.collection(eventsTable).findOne(query).then((result) => {

        if(!result) {
          return reply({ "statusCode": 400, "error": "Bad request", 'message': 'No record found for id: ' + request.params.id }).code(400);
        }

        if(request.payload.event_options) {
          request.payload.event_options.forEach((requestOption) => {
            let foundit = false;
            result.event_options.forEach((resultOption) => {
              if(resultOption.event_option_name == requestOption.event_option_name) {
                resultOption.event_option_value = requestOption.event_option_value;
                foundit = true;
              }
            });

            if (!foundit) {
              result.event_options.push(requestOption);
            }
          });
        }

        db.collection(eventsTable).findOneAndUpdate(query, { $set: request.payload },{returnOriginal: false}).then((result) => {

          let event = _renameAndClearFields(result.value);
          console.log(event);
          server.methods.publishUpdateEvent(event);

          return reply(JSON.stringify(result.lastErrorObject)).code(204);

        }).catch((err) => {
          console.log("ERROR:", err);
          return reply().code(503);
        });
      }).catch((err) => {
        console.log("ERROR:", err);
        return reply().code(503);
      });
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin', 'event_manager', 'event_logger']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        params: Joi.object({
          id: Joi.string().length(24).required()
        }),
        payload: Joi.object({
          event_author: Joi.string().min(1).max(100).optional(),
          ts: Joi.date().iso().optional(),
          event_value: Joi.string().min(1).max(100).optional(),
          event_options: Joi.array().items(Joi.object({
            event_option_name:Joi.string().required(),
            event_option_value:Joi.string().allow('').required()
          })).optional(),
          event_free_text: Joi.string().allow('').optional()
        }).required().min(1),
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          })
        }
      },
      description: 'Update a event record',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong> or <strong>event_logger</strong></p>',
      tags: ['events','auth','api'],
    }
  });

  server.route({
    method: 'DELETE',
    path: '/events/{id}',
    handler: function (request, reply) {

      let query = { _id: new ObjectID(request.params.id) };

      db.collection(eventsTable).findOne(query).then((result) => {
        if(!result) {
          return reply({ "statusCode": 404, 'message': 'No record found for id: ' + request.params.id }).code(404);
        }

        db.collection(eventsTable).findOneAndDelete(query).then((result) => {

          db.collection(eventAuxDataTable).find({ event_id: new ObjectID(request.params.id) }).toArray().then((aux_data_result) => {

            result.value.aux_data = aux_data_result;
            _renameAndClearFields(result.value);
            server.methods.publishDeleteEvent(result.value);

            db.collection(eventAuxDataTable).deleteMany({ event_id: new ObjectID(request.params.id) }).then(() => {
              return reply(result).code(204);
            }).catch((err) => {
              console.log("ERROR:", err);
              return reply().code(503);
            });
          }).catch((err) => {
            console.log("ERROR:", err);
            return reply().code(503);
          });  
        }).catch((err) => {
          console.log("ERROR:", err);
          return reply().code(503);
        });

      }).catch((err) => {
        console.log("ERROR:", err);
        return reply().code(503);
      });
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin', 'event_manager', 'event_logger']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        params: Joi.object({
          id: Joi.string().length(24).required()
        }),
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          })
        }
      },
      description: 'Delete an events record',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong> or <strong>event_logger</strong></p>',
      tags: [ 'events','auth','api'],
    }
  });

  server.route({
    method: 'DELETE',
    path: '/events/all',
    handler: function (request, reply) {

      // let query = {};

      db.collection(eventsTable).deleteMany().then((result) => {

        db.collection(eventAuxDataTable).deleteMany().then(() => {
          return reply(result).code(204);
        }).catch((err) => {
          console.log("ERROR:", err);
          return reply().code(503);
        });

      }).catch((err) => {
        console.log("ERROR:", err);
        return reply().code(503);
      });
    },
    config: {
      auth: {
        strategy: 'jwt',
        scope: ['admin']
      },
      validate: {
        headers: {
          authorization: Joi.string().required()
        },
        options: {
          allowUnknown: true
        }
      },
      response: {
        status: {
          400: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          }),
          401: Joi.object({
            statusCode: Joi.number().integer(),
            error: Joi.string(),
            message: Joi.string()
          })
        }
      },
      description: 'Delete ALL the event records',
      notes: '<p>Requires authorization via: <strong>JWT token</strong></p>\
        <p>Available to: <strong>admin</strong>, <strong>event_manager</strong> or <strong>event_logger</strong></p>',
      tags: [ 'events','auth','api'],
    }
  });

  return next();
};

exports.register.attributes = {
  name: 'routes-api-events',
  dependencies: ['hapi-mongodb']
};
