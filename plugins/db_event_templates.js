const Fs = require('fs');

const {
  eventTemplatesTable
} = require('../config/db_constants');

const init_data_filepath = './init_data/system_templates.json';

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

    let collection = null;
    let modified_data = [];
    console.log('Creating Event Templates Collection');
    try {
      collection = await db.createCollection(eventTemplatesTable);
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }

    console.log('Populating Event Templates Collection');
    try {
      const data = Fs.readFileSync(init_data_filepath, 'utf8');

      const init_data = JSON.parse(data);
      modified_data = init_data.map((template) => {

        template._id = ObjectID(template.id);
        delete template.id;
        return template;
      });

    }
    catch (err) {
      console.error('READ ERROR event_templates.json file:', err.code);
      throw (err);
    }

    try {
      await collection.insertMany(modified_data);
    }
    catch (err) {
      console.error('INSERT ERROR:', err.code);
      throw (err);
    }
  }
};
