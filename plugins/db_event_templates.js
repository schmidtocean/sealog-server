const fs = require('fs');

const {
  eventTemplatesTable
} = require('../config/db_constants');

const init_data_filepath = '../init_data/system_templates.json';

exports.plugin = {
  name: 'db_populate_event_templates',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const ObjectID = server.mongo.ObjectID;

    console.log('Searching for Event Templates Collection');
    const result = await db.listCollections({ name: eventTemplatesTable }).toArray();

    if (result.length) {
      if (process.env.NODE_ENV !== 'development') {
        console.log('Event Templates Collection already exists... we\'re done here.');
        return;
      }

      console.log('Event Templates Collection exists... dropping it!');
      try {
        await db.dropCollection(eventTemplatesTable);
      }
      catch (err) {
        console.log('DROP ERROR:', err.code);
        throw (err);
      }
    }

    console.log('Creating Event Templates Collection');
    try {
      const collection = await db.createCollection(eventTemplatesTable);
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }

    console.log('Populating Event Templates Collection');
    try {
      fs.readFile(init_data_filepath, 'utf8', (err, data) => {
        if (err) {
          console.error('Error reading JSON file:', err);
          throw (err);
        }

        const init_data = JSON.parse(data);

        const modified_data = init_data.map(template => {
          if (template.hasOwnProperty('id')) {
            template._id = ObjectID(template.id);
            delete template.id;
          }
          return template;
        });

        console.log(modified_data);
        // await collection.insertMany(modified_data);
      })
    } catch (err) {
      console.error('INSERT ERROR:', err.code);
      throw(err);
    }
  }
};
